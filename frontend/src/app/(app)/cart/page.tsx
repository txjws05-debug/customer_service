"use client";

// 购物车 + 结算页：浅色风格（白底 + slate + indigo）。
// 结算金额、优惠券、地址全部来自后端 preview，前端不做任何金额运算。

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Check,
  Loader2,
  MapPin,
  Minus,
  Package,
  Plus,
  ShoppingCart,
  Ticket,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import { getToken, getUser } from "@/lib/auth";
import {
  commerceUserId,
  money,
  shop,
  type Address,
  type AmountPreview,
  type Cart,
  type UserCoupon,
} from "@/lib/shop";

/** 券的门槛/额度文案；type 为 discount 时 rate 是 "0.900" 这类折扣率。 */
function couponBenefit(c: UserCoupon): string {
  if (c.type === "discount") {
    const rate = Number(c.rate ?? "");
    if (Number.isFinite(rate) && rate > 0) {
      // 0.9 → 9 折；不用 parseFloat 做金额，只是折扣展示
      return `打 ${(rate * 10).toFixed(1).replace(/\.0$/, "")} 折`;
    }
    return "折扣券";
  }
  return `减 ${money(c.amount)}`;
}

export default function CartPage() {
  const router = useRouter();

  const [user, setUser] = useState("u1001");
  const [cart, setCart] = useState<Cart | null>(null);
  const [addresses, setAddresses] = useState<Address[]>([]);
  const [coupons, setCoupons] = useState<UserCoupon[]>([]);
  const [preview, setPreview] = useState<AmountPreview | null>(null);

  const [loading, setLoading] = useState(true);
  const [busyItemId, setBusyItemId] = useState<number | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [previewError, setPreviewError] = useState("");

  const [couponCode, setCouponCode] = useState("");
  const [addressId, setAddressId] = useState<number | null>(null);
  const [createdOrderId, setCreatedOrderId] = useState<string | null>(null);
  const [failedCovers, setFailedCovers] = useState<number[]>([]);

  // 快速连点 ± 时，保证最后一次请求的数据生效
  const reqId = useRef(0);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const items = cart?.items ?? [];
  const selectedQuantity = cart?.selected_quantity ?? 0;

  const applyCart = useCallback((next: Cart) => {
    if (!alive.current) return;
    setCart(next);
  }, []);

  const fail = useCallback((err: unknown, fallback: string) => {
    toast.error(err instanceof Error ? err.message : fallback);
  }, []);

  /**
   * 拉购物车 + 地址 + 券（券的可用性依赖勾选商品金额，勾选变化后要重拉）。
   * 依赖只有 user，保证引用稳定，不会把调用它的 effect 反复触发。
   */
  const loadAll = useCallback(async () => {
    const id = ++reqId.current;
    try {
      const nextCart = await shop.cart(user);
      if (id !== reqId.current) return;
      setCart(nextCart);

      const [addr, couponList] = await Promise.all([
        shop.addresses(user),
        shop.coupons(user, nextCart.selected_amount),
      ]);
      if (id !== reqId.current) return;
      setAddresses(addr.addresses ?? []);
      setCoupons(couponList.coupons ?? []);
      // 用函数式 setState，避免把 addressId 变成 loadAll 的依赖
      setAddressId((current) => {
        if (current !== null) return current;
        const preferred =
          addr.addresses?.find((a) => a.is_default) ?? addr.addresses?.[0];
        return preferred ? preferred.id : current;
      });
    } catch (err) {
      if (id === reqId.current) fail(err, "购物车加载失败");
    }
  }, [user, fail]);

  // 登录守卫 + 商城账号 + 首次加载
  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    setUser(commerceUserId(getUser()?.username));
    let aliveOnce = true;
    (async () => {
      setLoading(true);
      await loadAll();
      if (aliveOnce) setLoading(false);
    })();
    return () => {
      aliveOnce = false;
    };
  }, [router, loadAll]);

  // 金额预览：勾选商品后才有意义
  useEffect(() => {
    let cancelled = false;
    if (!getToken()) return;
    if (!cart || cart.selected_quantity === 0) {
      setPreview(null);
      setPreviewError("");
      return;
    }
    (async () => {
      setPreviewing(true);
      try {
        const data = await shop.preview(user, {
          coupon_code: couponCode || null,
          address_id: addressId,
        });
        if (cancelled) return;
        setPreview(data);
        setPreviewError("");
      } catch (err) {
        if (cancelled) return;
        setPreview(null);
        setPreviewError(err instanceof Error ? err.message : "金额计算失败");
      } finally {
        if (!cancelled) setPreviewing(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [cart, user, couponCode, addressId]);

  async function mutate(action: () => Promise<Cart>, fallback: string) {
    try {
      const next = await action();
      applyCart(next);
      await loadAll();
    } catch (err) {
      fail(err, fallback);
    }
  }

  async function changeQuantity(itemId: number, quantity: number) {
    if (quantity < 1) return;
    setBusyItemId(itemId);
    try {
      await mutate(
        () => shop.updateCartItem(user, itemId, { quantity }),
        "修改数量失败",
      );
    } finally {
      setBusyItemId(null);
    }
  }

  async function toggleSelected(itemId: number, selected: boolean) {
    setBusyItemId(itemId);
    try {
      await mutate(
        () => shop.updateCartItem(user, itemId, { selected }),
        "修改勾选失败",
      );
    } finally {
      setBusyItemId(null);
    }
  }

  async function removeItem(itemId: number) {
    setBusyItemId(itemId);
    try {
      await mutate(() => shop.removeCartItem(user, itemId), "删除失败");
      toast.success("已从购物车移除");
    } finally {
      setBusyItemId(null);
    }
  }

  async function submitOrder() {
    if (cart?.selected_quantity === 0) {
      toast.error("请先勾选要结算的商品");
      return;
    }
    setSubmitting(true);
    try {
      const order = await shop.createOrder({
        user_id: user,
        address_id: addressId ?? undefined,
        coupon_code: couponCode || undefined,
      });
      setCreatedOrderId(order.order_id);
      // 结算成功后本地状态清空，再拉一次拿后端的最新购物车
      setPreview(null);
      setCouponCode("");
      const fresh = await shop.cart(user);
      applyCart(fresh);
      toast.success(`下单成功，订单号 ${order.order_id}（${order.status_desc}）`);
    } catch (err) {
      fail(err, "提交订单失败");
    } finally {
      setSubmitting(false);
    }
  }

  /** 券列表里某张券是否当前已选中 */
  const activeCoupon = coupons.find((c) => c.code === couponCode) ?? null;

  return (
    <div className="min-h-full">

      <main className="mx-auto max-w-6xl px-4 py-6">
        <h1 className="mb-4 flex items-center gap-2 text-lg font-semibold text-slate-800">
          <ShoppingCart size={18} className="text-indigo-500" />
          我的购物车
        </h1>

        {loading ? (
          <div className="flex items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white py-24 text-sm text-slate-500">
            <Loader2 size={16} className="animate-spin" />
            加载中…
          </div>
        ) : items.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-300 bg-white py-24 text-center">
            <Package size={40} className="mx-auto mb-3 text-slate-300" />
            <p className="text-sm text-slate-500">购物车还是空的</p>
            <Link
              href="/mall"
              className="mt-3 inline-block rounded-lg bg-indigo-500 px-4 py-2 text-sm text-white transition hover:bg-indigo-600"
            >
              去商城逛逛
            </Link>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            {/* 商品列表 */}
            <div className="flex flex-col gap-3 lg:col-span-2">
              {items.map((item) => {
                const busy = busyItemId === item.item_id;
                const showCover = !!item.cover_url && !failedCovers.includes(item.item_id);
                return (
                  <div
                    key={item.item_id}
                    className="flex gap-3 rounded-xl border border-slate-200 bg-white p-3"
                  >
                    <div className="flex items-center">
                      <button
                        onClick={() => toggleSelected(item.item_id, !item.selected)}
                        disabled={!item.available || busy}
                        title={item.selected ? "取消勾选" : "勾选结算"}
                        className={`flex h-5 w-5 items-center justify-center rounded border transition ${
                          item.selected
                            ? "border-indigo-500 bg-indigo-500 text-white"
                            : "border-slate-300 bg-white text-transparent hover:border-indigo-400"
                        } ${item.available ? "" : "cursor-not-allowed opacity-40"}`}
                      >
                        <Check size={13} />
                      </button>
                    </div>

                    <div className="flex h-20 w-20 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-slate-100">
                      {showCover ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={item.cover_url as string}
                          alt={item.title}
                          className="h-full w-full object-cover"
                          onError={() =>
                            setFailedCovers((prev) =>
                              prev.includes(item.item_id)
                                ? prev
                                : [...prev, item.item_id],
                            )
                          }
                        />
                      ) : (
                        <Package size={26} className="text-slate-300" />
                      )}
                    </div>

                    <div className="flex flex-1 flex-col gap-1">
                      <Link
                        href={`/mall/${item.product_id}`}
                        className="line-clamp-2 text-sm font-medium text-slate-800 transition hover:text-indigo-600"
                      >
                        {item.title}
                      </Link>
                      <span className="text-xs text-slate-500">{item.spec_text}</span>
                      <span className="text-sm text-slate-700">
                        单价 {money(item.price)}
                      </span>
                      {!item.available ? (
                        <span className="text-xs text-red-500">该规格已下架/无货</span>
                      ) : item.quantity > item.stock ? (
                        <span className="text-xs text-amber-600">
                          库存仅剩 {item.stock} 件
                        </span>
                      ) : null}
                    </div>

                    <div className="flex flex-col items-end justify-between">
                      <div className="flex items-center rounded-lg border border-slate-200">
                        <button
                          onClick={() => changeQuantity(item.item_id, item.quantity - 1)}
                          disabled={busy || item.quantity <= 1}
                          className="px-2 py-1 text-slate-600 transition hover:bg-slate-100 disabled:opacity-40"
                        >
                          <Minus size={13} />
                        </button>
                        <span className="w-10 border-x border-slate-200 py-1 text-center text-sm text-slate-900">
                          {busy ? "…" : item.quantity}
                        </span>
                        <button
                          onClick={() => changeQuantity(item.item_id, item.quantity + 1)}
                          disabled={busy || item.quantity >= item.stock}
                          className="px-2 py-1 text-slate-600 transition hover:bg-slate-100 disabled:opacity-40"
                        >
                          <Plus size={13} />
                        </button>
                      </div>

                      <span className="text-sm font-semibold text-indigo-600">
                        {money(item.subtotal)}
                      </span>

                      <button
                        onClick={() => removeItem(item.item_id)}
                        disabled={busy}
                        className="flex items-center gap-1 text-xs text-slate-400 transition hover:text-red-500 disabled:opacity-40"
                      >
                        <Trash2 size={13} />
                        删除
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* 结算面板 */}
            <div className="flex flex-col gap-4">
              {/* 地址 */}
              <section className="rounded-xl border border-slate-200 bg-white p-4">
                <h2 className="mb-3 flex items-center gap-1.5 text-sm font-semibold text-slate-800">
                  <MapPin size={15} className="text-indigo-500" />
                  收货地址
                </h2>
                {addresses.length === 0 ? (
                  <p className="text-sm text-slate-400">暂无收货地址</p>
                ) : (
                  <div className="flex flex-col gap-2">
                    {addresses.map((a) => (
                      <button
                        key={a.id}
                        onClick={() => setAddressId(a.id)}
                        className={`rounded-lg border px-3 py-2 text-left text-sm transition ${
                          addressId === a.id
                            ? "border-indigo-400 bg-indigo-50"
                            : "border-slate-200 bg-white hover:border-indigo-300"
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          <span className="text-slate-700">{a.receiver_name}</span>
                          <span className="text-xs text-slate-500">
                            {a.phone_masked}
                          </span>
                          {a.is_default ? (
                            <span className="rounded bg-slate-100 px-1.5 text-[11px] text-slate-500">
                              默认
                            </span>
                          ) : null}
                        </div>
                        <div className="mt-0.5 text-xs text-slate-500">
                          {a.full_address}
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </section>

              {/* 优惠券 */}
              <section className="rounded-xl border border-slate-200 bg-white p-4">
                <h2 className="mb-3 flex items-center gap-1.5 text-sm font-semibold text-slate-800">
                  <Ticket size={15} className="text-indigo-500" />
                  优惠券
                </h2>

                <button
                  onClick={() => setCouponCode("")}
                  className={`mb-2 w-full rounded-lg border px-3 py-2 text-left text-sm transition ${
                    couponCode === ""
                      ? "border-indigo-400 bg-indigo-50 text-indigo-600"
                      : "border-slate-200 text-slate-600 hover:border-indigo-300"
                  }`}
                >
                  不使用优惠券
                </button>

                {coupons.length === 0 ? (
                  <p className="text-sm text-slate-400">暂无可用优惠券</p>
                ) : (
                  <div className="flex flex-col gap-2">
                    {coupons.map((c) => (
                      <button
                        key={c.id}
                        onClick={() => {
                          if (!c.usable) return;
                          setCouponCode(c.code === couponCode ? "" : c.code);
                        }}
                        disabled={!c.usable}
                        className={`rounded-lg border px-3 py-2 text-left text-sm transition ${
                          couponCode === c.code
                            ? "border-indigo-400 bg-indigo-50"
                            : "border-slate-200 bg-white"
                        } ${c.usable ? "hover:border-indigo-300" : "cursor-not-allowed opacity-60"}`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-slate-700">{c.name}</span>
                          <span className="text-xs text-indigo-600">
                            {couponBenefit(c)}
                          </span>
                        </div>
                        <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                          <span>门槛 {money(c.threshold)}</span>
                          <span>有效期至 {c.end_at}</span>
                          <span
                            className={c.usable ? "text-emerald-600" : "text-slate-400"}
                          >
                            {c.usable ? "可用" : `不可用：${c.reason || "不满足条件"}`}
                          </span>
                        </div>
                      </button>
                    ))}
                  </div>
                )}

                {preview?.coupon_message ? (
                  <p className="mt-2 text-xs text-amber-600">{preview.coupon_message}</p>
                ) : null}
                {activeCoupon ? (
                  <p className="mt-2 text-xs text-indigo-600">
                    已选：{activeCoupon.name}（{couponBenefit(activeCoupon)}）
                  </p>
                ) : null}
              </section>

              {/* 金额 */}
              <section className="rounded-xl border border-slate-200 bg-white p-4">
                <h2 className="mb-3 text-sm font-semibold text-slate-800">金额明细</h2>

                {selectedQuantity === 0 ? (
                  <p className="text-sm text-slate-400">请先勾选要结算的商品</p>
                ) : previewError ? (
                  <p className="text-sm text-red-500">{previewError}</p>
                ) : preview ? (
                  <div className="flex flex-col gap-2 text-sm">
                    <div className="flex justify-between text-slate-600">
                      <span>商品金额</span>
                      <span>{money(preview.goods_amount)}</span>
                    </div>
                    <div className="flex justify-between text-slate-600">
                      <span>优惠</span>
                      <span className="text-red-500">
                        -{money(preview.discount_amount)}
                      </span>
                    </div>
                    <div className="flex justify-between text-slate-600">
                      <span>运费</span>
                      <span>
                        {money(preview.freight_amount)}
                        {preview.free_freight_threshold ? (
                          <span className="ml-1 text-xs text-slate-400">
                            （满 {money(preview.free_freight_threshold)} 免运费）
                          </span>
                        ) : null}
                      </span>
                    </div>
                    {preview.receiver_address ? (
                      <div className="text-xs text-slate-500">
                        收货：{preview.receiver_address}
                      </div>
                    ) : null}
                    <div className="mt-1 flex items-center justify-between border-t border-slate-100 pt-2">
                      <span className="text-slate-700">应付</span>
                      <span className="text-lg font-semibold text-indigo-600">
                        {money(preview.pay_amount)}
                      </span>
                    </div>
                    {preview.is_plus ? (
                      <span className="text-xs text-amber-600">
                        会员已享受专属优惠
                      </span>
                    ) : null}
                  </div>
                ) : (
                  <div className="flex items-center gap-2 text-sm text-slate-500">
                    <Loader2 size={14} className="animate-spin" />
                    计算中…
                  </div>
                )}

                <button
                  onClick={submitOrder}
                  disabled={
                    submitting || previewing || selectedQuantity === 0
                  }
                  className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-500 py-2.5 text-sm font-medium text-white transition hover:bg-indigo-600 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {submitting ? <Loader2 size={15} className="animate-spin" /> : null}
                  提交订单
                </button>

                {createdOrderId ? (
                  <div className="mt-3 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
                    订单号 {createdOrderId}，
                    <Link href="/orders" className="underline">
                      去我的订单付款
                    </Link>
                  </div>
                ) : null}
              </section>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
