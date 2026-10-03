"use client";

// 商品详情页：浅色风格（白底 + slate + indigo）。
// Next.js 16 的 params 是 Promise，客户端组件里用 use() 解包。

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Loader2, Package, ShoppingCart, Star, Truck } from "lucide-react";
import { toast } from "sonner";

import { getToken, getUser } from "@/lib/auth";
import {
  commerceUserId,
  money,
  shop,
  type ProductDetail,
  type Review,
  type ReviewList,
  type Sku,
} from "@/lib/shop";

/** 商品/SKU 是否可购买：SKU 本身就带状态和库存，两个条件都要满足。 */
function skuBuyable(sku: Sku): boolean {
  return sku.status === "在售" && sku.stock > 0;
}

function Stars({ value, size = 14 }: { value: number; size?: number }) {
  const filled = Number.isFinite(value) ? Math.round(value) : 0;
  return (
    <span className="flex items-center text-amber-500">
      {Array.from({ length: 5 }).map((_, i) => (
        <Star
          key={i}
          size={size}
          className={i < filled ? "fill-amber-400 text-amber-400" : "text-slate-300"}
        />
      ))}
    </span>
  );
}

function ReviewItem({ review }: { review: Review }) {
  return (
    <div className="border-b border-slate-100 py-4 last:border-b-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-slate-700">{review.nickname}</span>
        <Stars value={review.rating} size={12} />
        <span className="text-xs text-slate-400">{review.created_at}</span>
      </div>
      <p className="mt-2 whitespace-pre-wrap text-sm text-slate-700">
        {review.content}
      </p>
      {review.images?.length ? (
        <div className="mt-2 flex flex-wrap gap-2">
          {review.images.map((src, i) => (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              key={`${src}-${i}`}
              src={src}
              alt="评价图片"
              className="h-16 w-16 rounded-lg border border-slate-200 object-cover"
            />
          ))}
        </div>
      ) : null}
      {review.reply ? (
        <div className="mt-2 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
          <span className="text-slate-400">商家回复：</span>
          {review.reply}
        </div>
      ) : null}
      {review.append_content ? (
        <div className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-slate-700">
          <span className="text-amber-600">追评：</span>
          {review.append_content}
        </div>
      ) : null}
    </div>
  );
}

export default function ProductDetailPage({
  params,
}: {
  params: Promise<{ productId: string }>;
}) {
  const { productId } = use(params);

  const [user, setUser] = useState("u1001");
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [reviewList, setReviewList] = useState<ReviewList | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [skuCode, setSkuCode] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [adding, setAdding] = useState(false);
  const [buying, setBuying] = useState(false);
  const [coverFailed, setCoverFailed] = useState(false);
  const [addedToCart, setAddedToCart] = useState(false);
  const [createdOrderId, setCreatedOrderId] = useState<string | null>(null);

  useEffect(() => {
    if (!getToken()) {
      // 详情页不做跳转（params 解包后又要回跳比较绕），只提示；列表页会兜住未登录
      toast.error("登录状态已失效，请重新登录");
      return;
    }
    setUser(commerceUserId(getUser()?.username));
  }, []);

  // 商品主体 + 评价：评价失败不影响主体展示
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setNotFound(false);
    setProduct(null);
    setReviewList(null);
    setSkuCode("");
    setQuantity(1);
    setAddedToCart(false);
    setCreatedOrderId(null);

    (async () => {
      try {
        const detail = await shop.product(productId);
        if (!alive) return;
        setProduct(detail);
        const first = detail.skus?.find(skuBuyable) ?? detail.skus?.[0];
        setSkuCode(first ? first.sku_code : "");
      } catch (err) {
        if (!alive) return;
        const message = err instanceof Error ? err.message : "商品加载失败";
        // 接口层的错误信息已经本地化（404 时是后端的「商品不存在」）
        if (message.includes("404") || message.includes("不存在")) {
          setNotFound(true);
        } else {
          toast.error(message);
        }
      } finally {
        if (alive) setLoading(false);
      }
    })();

    (async () => {
      try {
        const reviews = await shop.productReviews(productId, 1);
        if (alive) setReviewList(reviews);
      } catch {
        // 评价区是次要内容，静默降级成「还没有评价」
      }
    })();

    return () => {
      alive = false;
    };
  }, [productId]);

  const selectedSku = product?.skus?.find((s) => s.sku_code === skuCode) ?? null;
  const buyable = selectedSku ? skuBuyable(selectedSku) : false;
  const stock = selectedSku?.stock ?? 0;
  const maxQuantity = Math.min(99, Math.max(1, stock));

  const changeQuantity = useCallback(
    (next: number) => {
      setQuantity(Math.min(maxQuantity, Math.max(1, next)));
    },
    [maxQuantity],
  );

  async function handleAddToCart() {
    if (!selectedSku || !buyable) {
      toast.error("请选择有货的规格");
      return;
    }
    setAdding(true);
    try {
      await shop.addToCart(user, selectedSku.sku_code, quantity);
      setAddedToCart(true);
      toast.success("已加入购物车");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "加入购物车失败");
    } finally {
      setAdding(false);
    }
  }

  async function handleBuyNow() {
    if (!selectedSku || !buyable) {
      toast.error("请选择有货的规格");
      return;
    }
    setBuying(true);
    try {
      const order = await shop.createOrder({
        user_id: user,
        items: [{ sku_code: selectedSku.sku_code, quantity }],
      });
      setCreatedOrderId(order.order_id);
      toast.success(`下单成功，订单号 ${order.order_id}（${order.status_desc}）`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "下单失败");
    } finally {
      setBuying(false);
    }
  }

  const reviews = reviewList?.reviews?.slice(0, 10) ?? [];

  return (
    <div className="min-h-full">

      <main className="mx-auto max-w-6xl px-4 py-6">
        <Link
          href="/shop"
          className="inline-flex items-center gap-1 text-sm text-slate-500 transition hover:text-indigo-600"
        >
          <ArrowLeft size={15} />
          返回商城
        </Link>

        {loading ? (
          <div className="mt-6 flex items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white py-24 text-sm text-slate-500">
            <Loader2 size={16} className="animate-spin" />
            加载中…
          </div>
        ) : notFound || !product ? (
          <div className="mt-6 rounded-xl border border-dashed border-slate-300 bg-white py-24 text-center">
            <Package size={40} className="mx-auto mb-3 text-slate-300" />
            <p className="text-sm text-slate-600">商品不存在或已下架</p>
            <Link
              href="/shop"
              className="mt-3 inline-block text-sm text-indigo-600 underline"
            >
              回商城看看别的商品
            </Link>
          </div>
        ) : (
          <>
            {/* 商品主体 */}
            <section className="mt-4 grid grid-cols-1 gap-6 rounded-xl border border-slate-200 bg-white p-4 lg:grid-cols-2 lg:p-6">
              <div className="flex h-80 items-center justify-center overflow-hidden rounded-xl bg-slate-100">
                {product.cover_url && !coverFailed ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={product.cover_url}
                    alt={product.title}
                    className="h-full w-full object-cover"
                    onError={() => setCoverFailed(true)}
                  />
                ) : (
                  <Package size={56} className="text-slate-300" />
                )}
              </div>

              <div className="flex flex-col gap-3">
                <h1 className="text-xl font-semibold text-slate-800">
                  {product.title}
                </h1>

                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
                  {product.brand ? <span>品牌：{product.brand}</span> : null}
                  {product.category ? <span>类目：{product.category}</span> : null}
                  <span
                    className={
                      product.status === "在售" ? "text-emerald-600" : "text-slate-400"
                    }
                  >
                    {product.status}
                  </span>
                </div>

                <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                  <Stars value={Number(product.rating_avg)} />
                  <span className="text-slate-600">{product.rating_avg}</span>
                  <span>· {product.rating_count} 条评价</span>
                  <span>· 已售 {product.sales_count}</span>
                </div>

                <div className="text-2xl font-semibold text-indigo-600">
                  {money(selectedSku?.price ?? product.skus?.[0]?.price)}
                </div>

                <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-600">
                  {product.description || "暂无商品描述"}
                </p>

                {/* SKU 规格 */}
                <div>
                  <div className="mb-2 text-sm text-slate-600">选择规格</div>
                  {product.skus?.length ? (
                    <div className="flex flex-col gap-2">
                      {product.skus.map((sku) => {
                        const ok = skuBuyable(sku);
                        const active = sku.sku_code === skuCode;
                        return (
                          <button
                            key={sku.sku_code}
                            onClick={() => {
                              setSkuCode(sku.sku_code);
                              setAddedToCart(false);
                              setCreatedOrderId(null);
                              setQuantity(1);
                            }}
                            disabled={!ok}
                            className={`flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2 text-left text-sm transition ${
                              active
                                ? "border-indigo-400 bg-indigo-50"
                                : "border-slate-200 bg-white hover:border-indigo-300"
                            } ${ok ? "" : "cursor-not-allowed opacity-50"}`}
                          >
                            <span className="text-slate-700">{sku.spec_text}</span>
                            <span className="flex items-center gap-2">
                              <span className="font-medium text-indigo-600">
                                {money(sku.price)}
                              </span>
                              {sku.original_price ? (
                                <span className="text-xs text-slate-400 line-through">
                                  {money(sku.original_price)}
                                </span>
                              ) : null}
                              <span className="text-xs text-slate-500">
                                {ok ? `库存 ${sku.stock}` : sku.status !== "在售" ? "已下架" : "无货"}
                              </span>
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="text-sm text-slate-400">该商品暂无可售规格</p>
                  )}
                </div>

                {/* 数量 */}
                <div className="flex items-center gap-3">
                  <span className="text-sm text-slate-600">数量</span>
                  <div className="flex items-center rounded-lg border border-slate-200">
                    <button
                      onClick={() => changeQuantity(quantity - 1)}
                      disabled={!buyable || quantity <= 1}
                      className="px-3 py-1.5 text-slate-600 transition hover:bg-slate-100 disabled:opacity-40"
                    >
                      −
                    </button>
                    <input
                      value={quantity}
                      onChange={(e) => {
                        const n = Number(e.target.value.replace(/\D/g, ""));
                        if (Number.isFinite(n) && n > 0) changeQuantity(n);
                        else setQuantity(1);
                      }}
                      disabled={!buyable}
                      className="w-14 border-x border-slate-200 py-1.5 text-center text-sm text-slate-900 outline-none disabled:bg-slate-50"
                    />
                    <button
                      onClick={() => changeQuantity(quantity + 1)}
                      disabled={!buyable || quantity >= maxQuantity}
                      className="px-3 py-1.5 text-slate-600 transition hover:bg-slate-100 disabled:opacity-40"
                    >
                      +
                    </button>
                  </div>
                  <span className="text-xs text-slate-400">
                    {buyable ? `最多可买 ${maxQuantity} 件` : "该规格暂不可购买"}
                  </span>
                </div>

                {/* 操作 */}
                <div className="flex flex-wrap items-center gap-3">
                  <button
                    onClick={handleAddToCart}
                    disabled={!buyable || adding}
                    className="flex items-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2.5 text-sm font-medium text-indigo-600 transition hover:bg-indigo-100 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {adding ? (
                      <Loader2 size={15} className="animate-spin" />
                    ) : (
                      <ShoppingCart size={15} />
                    )}
                    加入购物车
                  </button>
                  <button
                    onClick={handleBuyNow}
                    disabled={!buyable || buying}
                    className="flex items-center gap-1.5 rounded-lg bg-indigo-500 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-indigo-600 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {buying ? (
                      <Loader2 size={15} className="animate-spin" />
                    ) : (
                      <Truck size={15} />
                    )}
                    立即购买
                  </button>
                </div>

                {addedToCart ? (
                  <div className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
                    已加入购物车，
                    <Link href="/cart" className="underline">
                      去购物车结算
                    </Link>
                  </div>
                ) : null}

                {createdOrderId ? (
                  <div className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
                    订单已创建（待付款）：{createdOrderId}，
                    <Link href="/orders" className="underline">
                      去我的订单付款
                    </Link>
                  </div>
                ) : null}
              </div>
            </section>

            {/* 属性表 */}
            <section className="mt-4 rounded-xl border border-slate-200 bg-white p-4 lg:p-6">
              <h2 className="mb-3 text-sm font-semibold text-slate-800">商品参数</h2>
              {Object.keys(product.attributes ?? {}).length ? (
                <dl className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
                  {Object.entries(product.attributes).map(([key, value]) => (
                    <div
                      key={key}
                      className="flex gap-3 border-b border-slate-100 py-1.5 text-sm"
                    >
                      <dt className="w-24 shrink-0 text-slate-500">{key}</dt>
                      <dd className="text-slate-700">{value}</dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <p className="text-sm text-slate-400">暂无参数信息</p>
              )}
            </section>

            {/* 评价 */}
            <section className="mt-4 rounded-xl border border-slate-200 bg-white p-4 lg:p-6">
              <div className="mb-2 flex flex-wrap items-center gap-3">
                <h2 className="text-sm font-semibold text-slate-800">商品评价</h2>
                <Stars value={Number(reviewList?.rating_avg ?? product.rating_avg)} />
                <span className="text-sm text-slate-600">
                  {reviewList?.rating_avg ?? product.rating_avg}
                </span>
                <span className="text-xs text-slate-500">
                  {reviewList?.rating_count ?? product.rating_count} 条评价
                </span>
              </div>

              {reviews.length === 0 ? (
                <p className="py-8 text-center text-sm text-slate-400">还没有评价</p>
              ) : (
                <div>
                  {reviews.map((r) => (
                    <ReviewItem key={r.id} review={r} />
                  ))}
                </div>
              )}
            </section>
          </>
        )}
      </main>
    </div>
  );
}
