"use client";

// 我的：优惠券 / 积分与会员 / 收货地址。
// 沿用聊天页的浅色风格（白底 / slate 文字 / indigo 主色）。

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Award,
  Coins,
  Crown,
  Loader2,
  MapPin,
  Plus,
  Ticket,
} from "lucide-react";
import { toast } from "sonner";

import { ShopHeader } from "@/components/ShopHeader";
import { getToken, getUser } from "@/lib/auth";
import {
  commerceUserId,
  money,
  shop,
  type Address,
  type Points,
  type UserCoupon,
} from "@/lib/shop";

const COUPON_STATUS_LABEL: Record<string, string> = {
  unused: "未使用",
  used: "已使用",
  expired: "已过期",
};

const COUPON_STATUS_CLASS: Record<string, string> = {
  unused: "bg-emerald-50 text-emerald-600 border-emerald-200",
  used: "bg-slate-100 text-slate-500 border-slate-200",
  expired: "bg-slate-100 text-slate-400 border-slate-200",
};

function Section({
  title,
  icon: Icon,
  extra,
  children,
}: {
  title: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  extra?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-800">
          <Icon size={16} className="text-indigo-500" />
          {title}
        </h2>
        {extra}
      </div>
      {children}
    </section>
  );
}

/** 折扣券显示：「0.900」→「9 折」，「0.850」→「8.5 折」。 */
function discountText(rate?: string | null): string {
  if (!rate) return "折扣券";
  const percent = Math.round(Number(rate) * 1000) / 100;
  if (!Number.isFinite(percent)) return "折扣券";
  return `${percent / 10} 折`;
}

function CouponCard({ coupon }: { coupon: UserCoupon }) {
  const isFullReduce = coupon.type === "full_reduce";
  const available = coupon.usable && coupon.status === "unused";

  return (
    <div
      className={`rounded-xl border p-3 ${
        available
          ? "border-indigo-200 bg-white"
          : "border-slate-200 bg-slate-50 opacity-70"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-slate-800">
            {coupon.name}
          </p>
          <p className="mt-0.5 text-xs text-slate-500">
            满 {money(coupon.threshold)} 可用
          </p>
        </div>
        <span
          className={`flex-none rounded-full border px-2 py-0.5 text-xs ${
            COUPON_STATUS_CLASS[coupon.status] ?? COUPON_STATUS_CLASS.used
          }`}
        >
          {COUPON_STATUS_LABEL[coupon.status] ?? coupon.status}
        </span>
      </div>

      <p className="mt-2 text-lg font-semibold text-indigo-600">
        {isFullReduce
          ? `减 ${money(coupon.amount)}`
          : discountText(coupon.rate)}
      </p>

      <p className="mt-1 text-xs text-slate-500">
        有效期至 {new Date(coupon.end_at).toLocaleString("zh-CN")}
      </p>

      {!coupon.usable && (
        <p className="mt-1 text-xs text-amber-600">
          暂不可用：{coupon.reason || "不满足使用条件"}
        </p>
      )}
    </div>
  );
}

function PointsSection({ data }: { data: Points }) {
  const gap = Math.max(0, data.next_level_points - data.points);
  const ledger = data.ledger ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-lg bg-slate-50 p-3">
          <p className="text-xs text-slate-500">当前积分</p>
          <p className="mt-1 text-lg font-semibold text-slate-900">
            {data.points}
          </p>
        </div>
        <div className="rounded-lg bg-slate-50 p-3">
          <p className="text-xs text-slate-500">会员等级</p>
          <p className="mt-1 text-lg font-semibold text-slate-900">{data.level}</p>
        </div>
        <div className="rounded-lg bg-slate-50 p-3">
          <p className="text-xs text-slate-500">成长值</p>
          <p className="mt-1 text-lg font-semibold text-slate-900">{data.growth}</p>
        </div>
        <div className="rounded-lg bg-slate-50 p-3">
          <p className="text-xs text-slate-500">距离下一等级</p>
          <p className="mt-1 text-lg font-semibold text-slate-900">
            {gap === 0 ? "已达成" : `还差 ${gap}`}
          </p>
        </div>
      </div>

      <p className="text-xs text-slate-500">
        下一等级所需积分：{data.next_level_points}
      </p>

      <p
        className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${
          data.is_plus
            ? "border-amber-200 bg-amber-50 text-amber-700"
            : "border-slate-200 bg-slate-50 text-slate-500"
        }`}
      >
        <Crown size={15} />
        {data.is_plus
          ? "PLUS 会员：免运费 + 双倍积分"
          : "未开通 PLUS 会员"}
      </p>

      <div>
        <h3 className="mb-2 text-sm font-medium text-slate-700">积分流水</h3>
        {ledger.length === 0 ? (
          <p className="text-sm text-slate-400">暂无积分流水</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-slate-500">
                  <th className="pb-2 font-normal">变动</th>
                  <th className="pb-2 font-normal">余额</th>
                  <th className="pb-2 font-normal">原因</th>
                  <th className="pb-2 text-right font-normal">时间</th>
                </tr>
              </thead>
              <tbody>
                {ledger.map((log, index) => (
                  <tr
                    key={`${log.created_at}-${index}`}
                    className="border-t border-slate-100"
                  >
                    <td
                      className={`py-2 pr-2 font-medium ${
                        log.change >= 0 ? "text-emerald-600" : "text-red-500"
                      }`}
                    >
                      {log.change >= 0 ? `+${log.change}` : log.change}
                    </td>
                    <td className="py-2 pr-2 text-slate-700">
                      {log.balance_after}
                    </td>
                    <td className="py-2 pr-2 text-slate-600">
                      {log.reason}
                      {log.order_id && (
                        <span className="ml-1 text-xs text-slate-400">
                          （订单 {log.order_id}）
                        </span>
                      )}
                    </td>
                    <td className="py-2 text-right text-xs text-slate-500">
                      {new Date(log.created_at).toLocaleString("zh-CN")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

export default function MePage() {
  const router = useRouter();
  const [user, setUser] = useState<string | null>(null);

  const [coupons, setCoupons] = useState<UserCoupon[]>([]);
  const [usableCount, setUsableCount] = useState(0);
  const [points, setPoints] = useState<Points | null>(null);
  const [addresses, setAddresses] = useState<Address[]>([]);

  const [couponError, setCouponError] = useState("");
  const [pointsError, setPointsError] = useState("");
  const [addressError, setAddressError] = useState("");
  const [loading, setLoading] = useState(true);

  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    receiver_name: "",
    phone_masked: "",
    province: "",
    city: "",
    district: "",
    detail: "",
    is_default: false,
  });

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

    const [couponResult, pointsResult, addressResult] = await Promise.allSettled([
      shop.coupons(user),
      shop.points(user),
      shop.addresses(user),
    ]);

    if (couponResult.status === "fulfilled") {
      setCoupons(couponResult.value.coupons ?? []);
      setUsableCount(couponResult.value.usable_count);
      setCouponError("");
    } else {
      const message = couponResult.reason instanceof Error
        ? couponResult.reason.message
        : "优惠券加载失败";
      setCoupons([]);
      setCouponError(message);
      toast.error(message);
    }

    if (pointsResult.status === "fulfilled") {
      setPoints(pointsResult.value);
      setPointsError("");
    } else {
      const message = pointsResult.reason instanceof Error
        ? pointsResult.reason.message
        : "积分加载失败";
      setPoints(null);
      setPointsError(message);
      toast.error(message);
    }

    if (addressResult.status === "fulfilled") {
      setAddresses(addressResult.value.addresses ?? []);
      setAddressError("");
    } else {
      const message = addressResult.reason instanceof Error
        ? addressResult.reason.message
        : "地址加载失败";
      setAddresses([]);
      setAddressError(message);
      toast.error(message);
    }

    setLoading(false);
  }, [user]);

  useEffect(() => {
    void load();
  }, [load]);

  function updateForm<K extends keyof typeof form>(
    key: K,
    value: (typeof form)[K],
  ) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function submitAddress(e: React.FormEvent) {
    e.preventDefault();
    if (!user) return;
    if (!form.receiver_name.trim()) {
      toast.error("请填写收货人");
      return;
    }
    if (!/^\d{3}\*{4}\d{4}$/.test(form.phone_masked.trim())) {
      toast.error("手机号请按脱敏格式填写，例如 138****1234");
      return;
    }
    if (!form.detail.trim()) {
      toast.error("请填写详细地址");
      return;
    }

    setSaving(true);
    try {
      // 注意：@/lib/shop 里 createAddress 的形参类型是
      // Omit<Address, "id" | "full_address">，而 Address 没有
      // province / city / district / detail 字段，所以这里会报 TS2353，
      // 需要把 shop.createAddress 的 body 形参改成下面这个对象类型。
      // 这是共享模块（由他人维护）的类型声明与接口约定不一致，本文件不改它。
      const payload: {
        receiver_name: string;
        phone_masked: string;
        province: string;
        city: string;
        district: string;
        detail: string;
        is_default: boolean;
      } = {
        receiver_name: form.receiver_name.trim(),
        phone_masked: form.phone_masked.trim(),
        province: form.province.trim(),
        city: form.city.trim(),
        district: form.district.trim(),
        detail: form.detail.trim(),
        is_default: form.is_default,
      };
      const created = await shop.createAddress(user, payload);
      toast.success(`已新增收货地址：${created.full_address}`);
      setForm({
        receiver_name: "",
        phone_masked: "",
        province: "",
        city: "",
        district: "",
        detail: "",
        is_default: false,
      });
      setShowForm(false);
      await load();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  const inputClass =
    "rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-none placeholder:text-slate-400 focus:border-indigo-400";

  return (
    <div className="min-h-screen bg-slate-50">
      <ShopHeader />

      <main className="mx-auto flex max-w-4xl flex-col gap-4 px-4 py-6">
        <h1 className="text-lg font-semibold text-slate-800">我的</h1>

        {loading ? (
          <div className="flex items-center justify-center gap-2 py-20 text-slate-400">
            <Loader2 className="animate-spin" size={18} />
            <span className="text-sm">加载中…</span>
          </div>
        ) : (
          <>
            {/* 优惠券 */}
            <Section
              title="优惠券"
              icon={Ticket}
              extra={
                <span className="text-xs text-slate-500">
                  共 {coupons.length} 张 · 可用 {usableCount} 张
                </span>
              }
            >
              {couponError ? (
                <p className="text-sm text-red-500">{couponError}</p>
              ) : coupons.length === 0 ? (
                <p className="text-sm text-slate-400">暂无优惠券</p>
              ) : (
                <div className="grid gap-3 sm:grid-cols-2">
                  {coupons.map((coupon) => (
                    <CouponCard key={coupon.id} coupon={coupon} />
                  ))}
                </div>
              )}
            </Section>

            {/* 积分与会员 */}
            <Section title="积分与会员" icon={Coins}>
              {pointsError ? (
                <p className="text-sm text-red-500">{pointsError}</p>
              ) : points ? (
                <PointsSection data={points} />
              ) : (
                <p className="text-sm text-slate-400">暂无积分信息</p>
              )}
            </Section>

            {/* 收货地址 */}
            <Section
              title="收货地址"
              icon={MapPin}
              extra={
                <button
                  onClick={() => setShowForm((v) => !v)}
                  className="flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-600 transition hover:border-indigo-300 hover:text-indigo-600"
                >
                  <Plus size={13} />
                  {showForm ? "收起新增表单" : "新增地址"}
                </button>
              }
            >
              {showForm && (
                <form
                  onSubmit={submitAddress}
                  className="mb-4 grid gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3 sm:grid-cols-2"
                >
                  <input
                    value={form.receiver_name}
                    onChange={(e) => updateForm("receiver_name", e.target.value)}
                    placeholder="收货人（必填）"
                    className={inputClass}
                  />
                  <input
                    value={form.phone_masked}
                    onChange={(e) => updateForm("phone_masked", e.target.value)}
                    placeholder="脱敏手机号，如 138****1234（必填）"
                    className={inputClass}
                  />
                  <input
                    value={form.province}
                    onChange={(e) => updateForm("province", e.target.value)}
                    placeholder="省"
                    className={inputClass}
                  />
                  <input
                    value={form.city}
                    onChange={(e) => updateForm("city", e.target.value)}
                    placeholder="市"
                    className={inputClass}
                  />
                  <input
                    value={form.district}
                    onChange={(e) => updateForm("district", e.target.value)}
                    placeholder="区/县"
                    className={inputClass}
                  />
                  <input
                    value={form.detail}
                    onChange={(e) => updateForm("detail", e.target.value)}
                    placeholder="详细地址（必填）"
                    className={inputClass}
                  />
                  <label className="flex items-center gap-2 text-sm text-slate-600">
                    <input
                      type="checkbox"
                      checked={form.is_default}
                      onChange={(e) => updateForm("is_default", e.target.checked)}
                    />
                    设为默认地址
                  </label>
                  <button
                    type="submit"
                    disabled={saving}
                    className="justify-self-start rounded-lg bg-indigo-500 px-4 py-2 text-sm text-white transition hover:bg-indigo-600 disabled:opacity-50"
                  >
                    {saving ? "保存中…" : "保存地址"}
                  </button>
                  <p className="text-xs text-slate-400 sm:col-span-2">
                    说明：手机号按脱敏格式直接保存，页面与后端只处理脱敏号码。
                  </p>
                </form>
              )}

              {addressError ? (
                <p className="text-sm text-red-500">{addressError}</p>
              ) : addresses.length === 0 ? (
                <p className="text-sm text-slate-400">还没有收货地址，点右上角新增</p>
              ) : (
                <ul className="flex flex-col gap-2">
                  {addresses.map((address) => (
                    <li
                      key={address.id}
                      className="rounded-lg border border-slate-200 bg-slate-50 p-3"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium text-slate-800">
                          {address.receiver_name}
                        </span>
                        <span className="text-xs text-slate-500">
                          {address.phone_masked}
                        </span>
                        {address.is_default && (
                          <span className="rounded-full border border-indigo-200 bg-indigo-50 px-2 py-0.5 text-[11px] text-indigo-600">
                            默认
                          </span>
                        )}
                      </div>
                      <p className="mt-1 text-sm text-slate-600">
                        {address.full_address}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </Section>
          </>
        )}

        {!loading && !points && !couponError && !pointsError && !addressError && (
          <p className="flex items-center justify-center gap-1.5 text-xs text-slate-400">
            <Award size={13} />
            数据来自商城中台，登录后自动同步
          </p>
        )}
      </main>
    </div>
  );
}
