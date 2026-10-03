// 交易域（电商中台 /shop/*）的类型与客户端。
//
// 全部走相对路径 /shop/...：
//   - 生产：Caddy 把 /shop/* 转发到中台（deploy/Caddyfile）
//   - 本地开发：next.config.ts 的 rewrites 转发到 127.0.0.1:18081
// 这样前端代码里不出现 host、不跨域，和 /api/* 的处理方式保持一致。
//
// 金额字段后端用 Decimal 序列化，JSON 里是字符串（如 "8999.00"），
// 因此类型统一为 string，展示时用 money() 处理，避免浮点误差。

import { getToken } from "./auth";

export interface ApiEnvelope<T> {
  code: number;
  message: string;
  data: T;
}

// ============================================================ 类型
export interface Category {
  id: number;
  name: string;
  product_count: number;
}

export interface ProductListItem {
  product_id: string;
  title: string;
  price: string;
  cover_url?: string | null;
  category?: string | null;
  brand?: string | null;
  stock_status: string;
  rating_avg: string;
  rating_count: number;
  sales_count: number;
}

export interface ProductListData {
  total: number;
  page: number;
  page_size: number;
  keyword?: string | null;
  items: ProductListItem[];
}

export interface Sku {
  sku_id: number;
  sku_code: string;
  spec: Record<string, string>;
  spec_text: string;
  price: string;
  original_price?: string | null;
  stock: number;
  status: string;
}

export interface ProductDetail {
  product_id: string;
  title: string;
  description: string;
  cover_url?: string | null;
  category?: string | null;
  brand?: string | null;
  status: string;
  rating_avg: string;
  rating_count: number;
  sales_count: number;
  attributes: Record<string, string>;
  skus: Sku[];
}

export interface CartLine {
  item_id: number;
  sku_id: number;
  sku_code: string;
  product_id: string;
  title: string;
  spec_text: string;
  cover_url?: string | null;
  price: string;
  quantity: number;
  selected: boolean;
  stock: number;
  available: boolean;
  subtotal: string;
}

export interface Cart {
  user_id: string;
  items: CartLine[];
  total_quantity: number;
  selected_quantity: number;
  selected_amount: string;
}

export interface Address {
  id: number;
  receiver_name: string;
  phone_masked: string;
  full_address: string;
  is_default: boolean;
}

/** 新增地址的请求体：响应里的 full_address 是拼接结果，创建时要传分段字段。 */
export interface AddressCreate {
  receiver_name: string;
  phone_masked: string;
  province: string;
  city: string;
  district: string;
  detail: string;
  is_default?: boolean;
}

export interface CouponInfo {
  code: string;
  name: string;
  type: string;
  threshold: string;
  amount?: string | null;
  rate?: string | null;
  end_at: string;
}

export interface UserCoupon extends CouponInfo {
  id: number;
  status: string;
  usable: boolean;
  reason: string;
}

export interface UserCouponList {
  user_id: string;
  total: number;
  usable_count: number;
  coupons: UserCoupon[];
}

export interface PointsLog {
  change: number;
  balance_after: number;
  reason: string;
  created_at: string;
  order_id?: string | null;
}

export interface Points {
  user_id: string;
  nickname: string;
  level: string;
  is_plus: boolean;
  points: number;
  growth: number;
  next_level_points: number;
  ledger: PointsLog[];
}

export interface AmountPreview {
  goods_amount: string;
  discount_amount: string;
  freight_amount: string;
  pay_amount: string;
  is_plus: boolean;
  free_freight_threshold: string;
  coupon?: CouponInfo | null;
  coupon_message: string;
  address_id?: number | null;
  receiver_address?: string | null;
}

export interface OrderCreated {
  order_id: string;
  status: string;
  status_desc: string;
  goods_amount: string;
  discount_amount: string;
  freight_amount: string;
  pay_amount: string;
  coupon_code?: string | null;
  expires_in_minutes: number;
}

export interface OrderListItem {
  order_id: string;
  status: string;
  status_desc: string;
  pay_amount: string;
  quantity: number;
  title: string;
  cover_url?: string | null;
  created_at: string;
}

export interface OrderList {
  user_id: string;
  total: number;
  orders: OrderListItem[];
}

export interface OrderItem {
  product_id: string;
  title: string;
  spec_text?: string | null;
  quantity: number;
  price: string;
  subtotal: string;
}

export interface OrderStatusLog {
  from_status?: string | null;
  to_status: string;
  operator: string;
  remark?: string | null;
  created_at: string;
}

export interface OrderDetail {
  order_id: string;
  status: string;
  status_desc: string;
  created_at: string;
  paid_at?: string | null;
  shipped_at?: string | null;
  received_at?: string | null;
  goods_amount: string;
  discount_amount: string;
  freight_amount: string;
  pay_amount: string;
  is_plus: boolean;
  receiver_name: string;
  receiver_phone_masked: string;
  receiver_address: string;
  logistics_company?: string | null;
  tracking_number?: string | null;
  items: OrderItem[];
  status_logs: OrderStatusLog[];
  can_pay: boolean;
  can_cancel: boolean;
  can_receive: boolean;
}

export interface PayResult {
  order_id: string;
  trade_no: string;
  channel: string;
  amount: string;
  status: string;
  status_desc: string;
  paid_at: string;
}

export interface OrderActionResult {
  order_id: string;
  status: string;
  status_desc: string;
  refunded_points: number;
  earned_points: number;
  pay_amount?: string | null;
}

export interface AfterSaleTicket {
  ticket_no: string;
  order_id: string;
  type: string;
  type_desc: string;
  status: string;
  status_desc: string;
  reason: string;
  evidence: string[];
  refund_amount: string;
  remark?: string | null;
  created_at: string;
  updated_at: string;
  can_cancel: boolean;
  can_return: boolean;
}

export interface AfterSaleList {
  user_id: string;
  total: number;
  tickets: AfterSaleTicket[];
}

export interface Review {
  id: number;
  order_id: string;
  product_id: string;
  rating: number;
  content: string;
  images: string[];
  reply?: string | null;
  append_content?: string | null;
  nickname: string;
  created_at: string;
}

export interface ReviewList {
  product_id?: string | null;
  total: number;
  rating_avg: string;
  rating_count: number;
  reviews: Review[];
}

export interface AdminOrderListItem {
  order_id: string;
  user_id: string;
  nickname: string;
  status: string;
  status_desc: string;
  pay_amount: string;
  quantity: number;
  title: string;
  created_at: string;
  paid_at?: string | null;
  logistics_company?: string | null;
  tracking_number?: string | null;
}

export interface AdminOrderList {
  total: number;
  page: number;
  page_size: number;
  status_counts: Record<string, number>;
  orders: AdminOrderListItem[];
}

export interface Fulfillment {
  order_id: string;
  status: string;
  status_desc: string;
  logistics_company?: string | null;
  tracking_number?: string | null;
  latest_trace?: string | null;
}

export interface StockInfo {
  sku_code: string;
  product_id: string;
  title: string;
  spec_text: string;
  stock: number;
  change: number;
  status: string;
}

export interface LowStock {
  sku_code: string;
  product_id: string;
  title: string;
  spec_text: string;
  stock: number;
}

export interface AdminCoupon {
  code: string;
  name: string;
  type: string;
  threshold: string;
  amount?: string | null;
  rate?: string | null;
  start_at: string;
  end_at: string;
  total: number;
  claimed: number;
  used_count: number;
  per_user_limit: number;
}

export interface Stats {
  gmv: string;
  paid_order_count: number;
  finished_order_count: number;
  canceled_order_count: number;
  status_counts: Record<string, number>;
  after_sale_count: number;
  after_sale_rate: string;
  coupon_issued: number;
  coupon_used: number;
  points_issued: number;
  user_count: number;
  product_count: number;
  low_stock: LowStock[];
  top_products: { product_id: string; title: string; quantity: number; amount: string }[];
}

// ============================================================ 请求层
async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const res = await fetch(`/shop${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  });
  if (!res.ok) {
    // 中台的业务失败是 {code, message}，参数校验失败是 FastAPI 的 {detail}
    let detail = `请求失败（${res.status}）`;
    try {
      const body = await res.json();
      if (body?.message) detail = body.message;
      else if (body?.detail) detail = body.detail;
    } catch {}
    throw new Error(detail);
  }
  const body = (await res.json()) as ApiEnvelope<T>;
  return body.data;
}

const get = <T,>(path: string) => request<T>(path);
const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) });
const patch = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(body ?? {}) });
const del = <T,>(path: string) => request<T>(path, { method: "DELETE" });

function qs(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

// ============================================================ 接口
export const shop = {
  // 商品
  categories: () => get<Category[]>("/categories"),
  products: (params: {
    q?: string; category_id?: number; min_price?: string; max_price?: string;
    sort?: string; page?: number; page_size?: number;
  } = {}) => get<ProductListData>(`/products${qs(params)}`),
  product: (productId: string) => get<ProductDetail>(`/products/${productId}`),
  productReviews: (productId: string, page = 1) =>
    get<ReviewList>(`/products/${productId}/reviews${qs({ page, page_size: 10 })}`),

  // 购物车
  cart: (user: string) => get<Cart>(`/users/${user}/cart`),
  addToCart: (user: string, skuCode: string, quantity = 1) =>
    post<Cart>(`/users/${user}/cart`, { sku_code: skuCode, quantity }),
  updateCartItem: (user: string, itemId: number,
                   body: { quantity?: number; selected?: boolean }) =>
    patch<Cart>(`/users/${user}/cart/${itemId}`, body),
  removeCartItem: (user: string, itemId: number) =>
    del<Cart>(`/users/${user}/cart/${itemId}`),
  preview: (user: string, body: { coupon_code?: string | null; address_id?: number | null } = {}) =>
    post<AmountPreview>(`/users/${user}/cart/preview`, body),

  // 地址 / 券 / 积分
  addresses: (user: string) =>
    get<{ user_id: string; addresses: Address[] }>(`/users/${user}/addresses`),
  createAddress: (user: string, body: AddressCreate) =>
    post<Address>(`/users/${user}/addresses`, body),
  coupons: (user: string, goodsAmount?: string) =>
    get<UserCouponList>(`/users/${user}/coupons${qs({ goods_amount: goodsAmount })}`),
  points: (user: string) => get<Points>(`/users/${user}/points`),

  // 订单
  orders: (user: string, status?: string) =>
    get<OrderList>(`/users/${user}/orders${qs({ status })}`),
  order: (orderId: string) => get<OrderDetail>(`/orders/${orderId}`),
  createOrder: (body: { user_id: string; address_id?: number; coupon_code?: string;
                        items?: { sku_code: string; quantity: number }[] }) =>
    post<OrderCreated>("/orders", body),
  payOrder: (orderId: string, channel = "wechat") =>
    post<PayResult>(`/orders/${orderId}/pay`, { channel }),
  cancelOrder: (orderId: string, reason = "用户主动取消") =>
    post<OrderActionResult>(`/orders/${orderId}/cancel`, { reason }),
  receiveOrder: (orderId: string) =>
    post<OrderActionResult>(`/orders/${orderId}/receive`),

  // 售后
  applyAfterSale: (orderId: string, body: {
    user_id: string; type: string; reason: string;
    evidence?: string[]; refund_amount?: string;
  }) => post<AfterSaleTicket>(`/orders/${orderId}/after-sales`, body),
  afterSales: (user: string, status?: string) =>
    get<AfterSaleList>(`/users/${user}/after-sales${qs({ status })}`),
  afterSale: (ticketNo: string) => get<AfterSaleTicket>(`/after-sales/${ticketNo}`),
  cancelAfterSale: (ticketNo: string) =>
    post<AfterSaleTicket>(`/after-sales/${ticketNo}/cancel`),
  submitReturn: (ticketNo: string, body: { tracking_number: string; company?: string }) =>
    post<AfterSaleTicket>(`/after-sales/${ticketNo}/return`, body),

  // 评价
  createReviews: (orderId: string, body: {
    user_id: string;
    items: { product_id: string; rating: number; content: string; images?: string[] }[];
  }) => post<Review[]>(`/orders/${orderId}/reviews`, body),
  pendingReviews: (user: string) =>
    get<{ user_id: string; order_ids: string[] }>(`/users/${user}/pending-reviews`),
  appendReview: (user: string, reviewId: number, content: string) =>
    post<Review>(`/users/${user}/reviews/${reviewId}/append`, { content }),

  // 运营端
  admin: {
    orders: (params: { status?: string; user_id?: string; page?: number; page_size?: number } = {}) =>
      get<AdminOrderList>(`/admin/orders${qs(params)}`),
    ship: (orderId: string, body: { company?: string; tracking_number?: string } = {}) =>
      post<Fulfillment>(`/admin/orders/${orderId}/ship`, body),
    advance: (orderId: string, remark?: string) =>
      post<Fulfillment>(`/admin/orders/${orderId}/advance`, { remark }),
    afterSales: (status?: string) =>
      get<AfterSaleList>(`/admin/after-sales${qs({ status })}`),
    approveAfterSale: (ticketNo: string, remark?: string) =>
      post<AfterSaleTicket>(`/admin/after-sales/${ticketNo}/approve`, { remark }),
    rejectAfterSale: (ticketNo: string, remark?: string) =>
      post<AfterSaleTicket>(`/admin/after-sales/${ticketNo}/reject`, { remark }),
    receiveAfterSale: (ticketNo: string, remark?: string) =>
      post<AfterSaleTicket>(`/admin/after-sales/${ticketNo}/receive`, { remark }),
    completeAfterSale: (ticketNo: string, remark?: string) =>
      post<AfterSaleTicket>(`/admin/after-sales/${ticketNo}/complete`, { remark }),
    stats: () => get<Stats>("/admin/stats"),
    lowStock: (threshold = 10) => get<LowStock[]>(`/admin/low-stock${qs({ threshold })}`),
    updateStock: (skuCode: string, stock: number, reason = "运营调整") =>
      patch<StockInfo>(`/admin/skus/${skuCode}/stock`, { stock, reason }),
    coupons: () => get<AdminCoupon[]>("/admin/coupons"),
    createCoupon: (body: {
      code: string; name: string; type: string; threshold?: string;
      amount?: string; rate?: string; days?: number; total?: number; per_user_limit?: number;
    }) => post<AdminCoupon>("/admin/coupons", body),
    grantCoupon: (code: string, userIds: string[]) =>
      post<{ code: string; granted: number; skipped: string[] }>(
        `/admin/coupons/${code}/grant`, { user_ids: userIds }),
  },
};

// ============================================================ 辅助
/** 金额展示：后端金额是字符串，直接拼 ¥ 即可，不做浮点运算。 */
export function money(value?: string | number | null): string {
  if (value === undefined || value === null || value === "") return "¥0.00";
  const text = String(value);
  return text.startsWith("¥") ? text : `¥${text}`;
}

/**
 * 当前登录用户对应的商城账号。
 *
 * 规则必须与后端 ws/utils/shop_client.resolve_commerce_user 保持一致：
 * 登录名本身就是商城号（u1001）就用它，否则用演示默认账号 u1001。
 * 不一致会导致「页面上看到的购物车/订单，和在线客服操作的不是同一个」。
 */
export function commerceUserId(username?: string | null): string {
  const name = (username ?? "").trim();
  return /^u\d+$/.test(name) ? name : "u1001";
}

export const ORDER_STATUSES = [
  "待付款", "待发货", "待揽收", "运输中", "待收货", "已完成", "已取消",
] as const;

export const AFTER_SALE_STATUS_LABEL: Record<string, string> = {
  submitted: "待审核",
  approved: "审核通过",
  rejected: "已驳回",
  returning: "寄回中",
  received: "商家已收货",
  completed: "已完成",
  canceled: "已撤销",
};
