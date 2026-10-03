"use client";

// 商品列表页：浅色风格（白底 + slate + indigo），与 /chat 保持一致。
// 数据全部来自 @/lib/shop，金额展示统一走 money()（后端金额是字符串）。

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Loader2, Package, Search, Star } from "lucide-react";
import { toast } from "sonner";

import { getToken, getUser } from "@/lib/auth";
import {
  commerceUserId,
  money,
  shop,
  type Category,
  type ProductListItem,
} from "@/lib/shop";

const PAGE_SIZE = 12;

const SORTS: { value: string; label: string }[] = [
  { value: "default", label: "综合" },
  { value: "sales", label: "销量" },
  { value: "rating", label: "评分" },
  { value: "price_asc", label: "价格从低到高" },
  { value: "price_desc", label: "价格从高到低" },
  { value: "newest", label: "最新" },
];

/** 评分展示：无评价时显示「暂无评价」，否则显示星标 + 平均分 + 评价数。 */
function Rating({ value, count }: { value: string; count: number }) {
  if (!count) {
    return <span className="text-xs text-slate-400">暂无评价</span>;
  }
  const score = Number(value);
  const filled = Number.isFinite(score) ? Math.round(score) : 0;
  return (
    <span className="flex items-center gap-1 text-xs text-slate-500">
      <span className="flex items-center text-amber-500">
        {Array.from({ length: 5 }).map((_, i) => (
          <Star
            key={i}
            size={12}
            className={i < filled ? "fill-amber-400 text-amber-400" : "text-slate-300"}
          />
        ))}
      </span>
      <span className="text-slate-600">{value}</span>
      <span>（{count}）</span>
    </span>
  );
}

/** 商品卡片。cover_url 可能为空或加载失败，两种情况都用 slate 占位块。 */
function ProductCard({
  item,
  broken,
  onBroken,
}: {
  item: ProductListItem;
  broken: boolean;
  onBroken: (productId: string) => void;
}) {
  const showCover = !!item.cover_url && !broken;
  const inStock = item.stock_status === "有货";

  return (
    <Link
      href={`/shop/${item.product_id}`}
      className="group flex flex-col overflow-hidden rounded-xl border border-slate-200 bg-white transition hover:border-indigo-300 hover:shadow-sm"
    >
      <div className="flex h-40 items-center justify-center overflow-hidden bg-slate-100">
        {showCover ? (
          // 商品图是后端返回的任意地址，用原生 img，不走 next/image 的域名白名单
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={item.cover_url as string}
            alt={item.title}
            className="h-full w-full object-cover"
            onError={() => onBroken(item.product_id)}
          />
        ) : (
          <Package size={36} className="text-slate-300" />
        )}
      </div>

      <div className="flex flex-1 flex-col gap-2 p-3">
        <h3 className="line-clamp-2 text-sm font-medium text-slate-800 group-hover:text-indigo-600">
          {item.title}
        </h3>

        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500">
          {item.brand ? <span>品牌：{item.brand}</span> : null}
          {item.category ? <span>类目：{item.category}</span> : null}
        </div>

        <div className="text-base font-semibold text-indigo-600">
          {money(item.price)}
        </div>

        <Rating value={item.rating_avg} count={item.rating_count} />

        <div className="mt-auto flex items-center justify-between text-xs text-slate-500">
          <span>已售 {item.sales_count}</span>
          <span className={inStock ? "text-emerald-600" : "text-slate-400"}>
            {item.stock_status || "库存未知"}
          </span>
        </div>
      </div>
    </Link>
  );
}

function CardSkeleton() {
  return (
    <div className="animate-pulse overflow-hidden rounded-xl border border-slate-200 bg-white">
      <div className="h-40 bg-slate-100" />
      <div className="space-y-2 p-3">
        <div className="h-4 w-4/5 rounded bg-slate-100" />
        <div className="h-3 w-2/5 rounded bg-slate-100" />
        <div className="h-4 w-1/3 rounded bg-slate-100" />
      </div>
    </div>
  );
}

export default function ShopPage() {
  const router = useRouter();

  const [user, setUser] = useState("u1001");
  const [categories, setCategories] = useState<Category[]>([]);

  const [keyword, setKeyword] = useState("");
  const [q, setQ] = useState("");
  const [categoryId, setCategoryId] = useState<number | null>(null);
  const [minPrice, setMinPrice] = useState("");
  const [maxPrice, setMaxPrice] = useState("");
  const [priceRange, setPriceRange] = useState<{ min: string; max: string }>({
    min: "",
    max: "",
  });
  const [sort, setSort] = useState("default");
  const [page, setPage] = useState(1);

  const [items, setItems] = useState<ProductListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState<string[]>([]);

  // 只为「快速切换筛选条件」防抖，保证最后一次请求的数据生效
  const reqId = useRef(0);

  // 未登录直接回登录页；同时把登录名换算成商城账号
  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    setUser(commerceUserId(getUser()?.username));
  }, [router]);

  // 类目只需要拉一次
  useEffect(() => {
    if (!getToken()) return;
    let alive = true;
    (async () => {
      try {
        const data = await shop.categories();
        if (alive) setCategories(data);
      } catch (err) {
        if (alive) {
          toast.error(err instanceof Error ? err.message : "类目加载失败");
        }
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const load = useCallback(async () => {
    if (!getToken()) return;
    const id = ++reqId.current;
    setLoading(true);
    try {
      const data = await shop.products({
        q: q || undefined,
        category_id: categoryId ?? undefined,
        min_price: priceRange.min || undefined,
        max_price: priceRange.max || undefined,
        sort,
        page,
        page_size: PAGE_SIZE,
      });
      if (id !== reqId.current) return;
      setItems(data.items ?? []);
      setTotal(data.total ?? 0);
    } catch (err) {
      if (id !== reqId.current) return;
      setItems([]);
      setTotal(0);
      toast.error(err instanceof Error ? err.message : "商品加载失败");
    } finally {
      if (id === reqId.current) setLoading(false);
    }
  }, [q, categoryId, priceRange.min, priceRange.max, sort, page]);

  useEffect(() => {
    void load();
  }, [load]);

  /** 任一筛选条件变化都要回到第 1 页，否则会停在一个越界的页码上。 */
  function applyFilter(next: () => void) {
    next();
    setPage(1);
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="min-h-full">

      <main className="mx-auto max-w-6xl px-4 py-6">
        {/* 搜索 + 排序 */}
        <div className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-4">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <div className="flex flex-1 items-center gap-2">
              <input
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") applyFilter(() => setQ(keyword.trim()));
                }}
                placeholder="搜索商品名称、品牌、关键词"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 outline-none transition focus:border-indigo-400"
              />
              <button
                onClick={() => applyFilter(() => setQ(keyword.trim()))}
                className="flex shrink-0 items-center gap-1 rounded-lg bg-indigo-500 px-3 py-2 text-sm text-white transition hover:bg-indigo-600"
              >
                <Search size={15} />
                搜索
              </button>
            </div>

            <select
              value={sort}
              onChange={(e) => applyFilter(() => setSort(e.target.value))}
              className="rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-700 outline-none transition focus:border-indigo-400"
            >
              {SORTS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>

          {/* 价格区间 */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-slate-500">价格区间</span>
            <input
              value={minPrice}
              onChange={(e) => setMinPrice(e.target.value)}
              inputMode="decimal"
              placeholder="最低价"
              className="w-24 rounded-lg border border-slate-200 px-2 py-1.5 text-sm text-slate-900 placeholder:text-slate-400 outline-none transition focus:border-indigo-400"
            />
            <span className="text-slate-400">—</span>
            <input
              value={maxPrice}
              onChange={(e) => setMaxPrice(e.target.value)}
              inputMode="decimal"
              placeholder="最高价"
              className="w-24 rounded-lg border border-slate-200 px-2 py-1.5 text-sm text-slate-900 placeholder:text-slate-400 outline-none transition focus:border-indigo-400"
            />
            <button
              onClick={() =>
                applyFilter(() =>
                  setPriceRange({ min: minPrice.trim(), max: maxPrice.trim() }),
                )
              }
              className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-600 transition hover:border-indigo-300 hover:text-indigo-600"
            >
              应用
            </button>
            {(priceRange.min || priceRange.max) && (
              <button
                onClick={() =>
                  applyFilter(() => {
                    setMinPrice("");
                    setMaxPrice("");
                    setPriceRange({ min: "", max: "" });
                  })
                }
                className="text-xs text-slate-400 underline hover:text-slate-600"
              >
                清除
              </button>
            )}
          </div>
        </div>

        {/* 类目 */}
        <div className="mt-4 flex flex-wrap gap-2">
          <button
            onClick={() => applyFilter(() => setCategoryId(null))}
            className={`rounded-full border px-3 py-1.5 text-sm transition ${
              categoryId === null
                ? "border-indigo-300 bg-indigo-50 text-indigo-600"
                : "border-slate-200 bg-white text-slate-600 hover:border-indigo-300"
            }`}
          >
            全部
          </button>
          {categories.map((c) => (
            <button
              key={c.id}
              onClick={() => applyFilter(() => setCategoryId(c.id))}
              className={`rounded-full border px-3 py-1.5 text-sm transition ${
                categoryId === c.id
                  ? "border-indigo-300 bg-indigo-50 text-indigo-600"
                  : "border-slate-200 bg-white text-slate-600 hover:border-indigo-300"
              }`}
            >
              {c.name}
              <span className="ml-1 text-xs text-slate-400">{c.product_count}</span>
            </button>
          ))}
        </div>

        {/* 列表 */}
        <div className="mt-5">
          <div className="mb-3 text-xs text-slate-500">
            共 {total} 件商品
            {q ? ` · 关键词「${q}」` : ""}
          </div>

          {loading ? (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <CardSkeleton key={i} />
              ))}
            </div>
          ) : items.length === 0 ? (
            <div className="rounded-xl border border-dashed border-slate-300 bg-white py-16 text-center">
              <Package size={40} className="mx-auto mb-3 text-slate-300" />
              <p className="text-sm text-slate-500">
                没有找到符合条件的商品，换个关键词试试
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {items.map((item) => (
                <ProductCard
                  key={item.product_id}
                  item={item}
                  broken={failed.includes(item.product_id)}
                  onBroken={(id) =>
                    setFailed((prev) => (prev.includes(id) ? prev : [...prev, id]))
                  }
                />
              ))}
            </div>
          )}
        </div>

        {/* 分页 */}
        {!loading && total > 0 && (
          <div className="mt-6 flex items-center justify-center gap-3 text-sm">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-slate-600 transition hover:border-indigo-300 hover:text-indigo-600 disabled:cursor-not-allowed disabled:opacity-40"
            >
              上一页
            </button>
            <span className="text-slate-500">
              第 {page} / {totalPages} 页
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-slate-600 transition hover:border-indigo-300 hover:text-indigo-600 disabled:cursor-not-allowed disabled:opacity-40"
            >
              下一页
            </button>
          </div>
        )}

        {/* 这里只是把商城账号暴露出来，方便和客服侧对照排查 */}
        <p className="mt-8 text-center text-xs text-slate-400">
          当前商城账号：{user}
        </p>
      </main>
    </div>
  );
}
