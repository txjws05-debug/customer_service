# atguigu ecommerce service

这是一个配套 `atguigu` 项目使用的电商业务服务（中台）。

它提供两块能力：

1. **只读查询接口**（根路径）：用户最近订单/商品、订单状态、物流、商品详情、
   发货提醒、退款申请 —— 客服 Agent 上线以来一直在用，路径与响应结构保持不变。
2. **交易域接口**（`/shop/*`）：商品规格与库存、购物车、地址、下单、支付、
   发货收货、优惠券、积分、售后工单、评价、商品搜索，以及运营管理端与看板。

也就是说：它从「给客服喂数据的只读服务」变成了一个**业务闭环完整的小型电商平台**。

初始化数据覆盖了多种典型状态，便于课堂演示：待付款、待发货、待揽收、运输中、
待收货、已完成、已取消；另有历史退款申请与发货提醒。

## 启动方式

本项目已并入仓库根目录的 `docker-compose.yml`，与客服 Agent 共用同一个
PostgreSQL 实例（pgvector 镜像），只是使用不同的库：

| 库名 | 使用者 |
| --- | --- |
| `customer_service` | 客服 Agent（对话状态、用户） |
| `commerce` | 本服务（用户、商品、订单、物流、交易域全部表） |

在仓库根目录统一启动：

```bash
cd /opt/customer_service
cp deploy/.env.example deploy/.env
cp deploy/backend.env.example deploy/backend.env
cp deploy/ecommerce.env.example deploy/ecommerce.env
docker compose --env-file deploy/.env up -d --build
```

首次启动时本服务会自动建表、**补齐新增列**并写入演示数据
（可用 `SEED_ON_STARTUP=false` 关闭）。

启动后默认地址：

- API: `http://127.0.0.1:18081`
- OpenAPI: `http://127.0.0.1:18081/docs`（交易域在 `/shop` 分组下）

## 数据库演进：为什么不引入 Alembic

`Base.metadata.create_all` 只建**新表**，不会给已存在的表加列 —— 而线上库早就
有 users/products/orders 了。本项目是单库、单人维护、部署即启动，引入迁移框架
的收益不抵成本，因此改用**幂等的轻量迁移**（`app/init_data.py` 的 `ensure_columns`）：

```sql
ALTER TABLE IF EXISTS orders ADD COLUMN IF NOT EXISTS pay_amount NUMERIC(10,2);
```

重复启动无副作用；新列补齐后由 `app/seed_shop.py` 做**幂等补种与回填**
（商品类目/价格、订单实付金额、各状态时间戳、会员标记、积分），
因此对老库执行一次重启即可完成升级。

## 接口一览

### 只读查询（根路径，客服 Agent 在用）

- `GET /health`
- `GET /users/{user_id}/orders`、`GET /users/{user_id}/products`
- `GET /orders/{order_id}`、`/status`、`/logistics`
- `GET /products/{product_id}`
- `POST /orders/{order_id}/shipping-reminders`、`/refund-applications`

### 交易域（`/shop/*`）

| 分组 | 接口 |
| --- | --- |
| 商品 | `GET /shop/categories`、`GET /shop/products`（关键词/类目/价格区间/排序/分页）、`GET /shop/products/{id}` |
| 购物车 | `GET/POST /shop/users/{uid}/cart`、`PATCH/DELETE /shop/users/{uid}/cart/{item_id}`、`POST .../cart/preview`（算钱预览） |
| 地址 | `GET/POST /shop/users/{uid}/addresses` |
| 营销 | `GET /shop/users/{uid}/coupons`、`GET /shop/users/{uid}/points` |
| 订单 | `POST /shop/orders`（下单）、`GET /shop/users/{uid}/orders`、`GET /shop/orders/{id}`、`POST /shop/orders/{id}/pay|/cancel|/receive` |
| 售后 | `POST /shop/orders/{id}/after-sales`、`GET /shop/users/{uid}/after-sales`、`GET /shop/after-sales/{ticket}`、`POST .../cancel`、`POST .../return` |
| 评价 | `POST /shop/orders/{id}/reviews`、`GET /shop/products/{id}/reviews`、`POST /shop/users/{uid}/reviews/{id}/append`、`GET /shop/users/{uid}/pending-reviews` |
| 运营端 | `GET /shop/admin/orders`、`POST .../ship`、`POST .../advance`、`GET /shop/admin/after-sales` + `approve/reject/receive/complete`、`PATCH /shop/admin/skus/{code}/stock`、`GET /shop/admin/low-stock`、`GET/POST /shop/admin/coupons`、`POST /shop/admin/coupons/{code}/grant`、`GET /shop/admin/stats` |

> ⚠️ 运营端接口目前**没有鉴权**，属于演示取舍：生产必须在网关加访问控制
> （`deploy/Caddyfile` 里的 `/shop/admin/*` 单独限制），或在服务层接入统一认证。

## 业务规则（都在 `app/shop_rules.py`，纯函数、可单测）

- **订单状态机**：`待付款 → 待发货 → 待揽收 → 运输中 → 待收货 → 已完成`，
  以及 `待付款/待发货 → 已取消`；未列出的流转一律拒绝（例如「已完成」不能再发货）。
- **待付款超时**：30 分钟未支付自动关单，**归还库存与优惠券**（读取订单时惰性执行，不需要定时任务）。
- **售后状态机**：`submitted → approved/rejected → returning → received → completed`，
  仅退款审核通过可直接完成；退货退款验收通过后**回滚库存**并写库存流水。
- **算钱**：实付 = 商品金额 − 优惠 + 运费；满 99 包邮、PLUS 免运费、否则 8 元；
  满减券不满门槛不抵扣，折扣券按 rate 减免，优惠额不超过商品金额，实付不为 0。
- **积分**：确认收货时发放，普通会员 1 元 1 分、PLUS 双倍；评价每条 10 分。
  不变量：`users.points == sum(points_ledger.change)`，任何一半缺失重跑补种即自愈。
- **库存**：下单用 `SELECT ... FOR UPDATE` 行锁扣减，避免并发超卖；
  每次变动都写 `inventory_logs`（下单/取消/超时关单/售后退货入库/运营调整）。
- **审计**：订单每次状态变化都写 `order_status_logs`（含操作方与备注）。

## 测试与联调

```bash
cd ecommerce-service-backend
uv run --locked pytest -q          # 规则单测 + 真库集成测试（无库时集成测试自动 skip）
```

集成测试用**真实 PostgreSQL**（不是 SQLite）：库存行锁、Numeric 金额、JSON 列
在 SQLite 上验证不了。CI 里由 job 的 `services: postgres` 提供，
并且**一旦有测试被 skip 就让 CI 红**，避免「集成测试没跑却显示通过」。

跨服务联调（客服 Agent → 中台，真实服务、真实数据库）：

```bash
python scripts/e2e_shop_flow.py --base-url http://127.0.0.1:18081 --user u1002
```

脚本按一条真实客户路径跑：加购 → 看购物车 → 查券 → 下单（用券）→ 未发货时收货
（应被拒）→ 支付 → 运营端发货并推进 → 确认收货（得积分）→ 申请售后 → 看订单 →
搜索商品；开头会先清空购物车、并动态挑一张可用券，因此可以反复执行。

压测（读路径吞吐/分位延迟 + 并发抢购是否超卖）：

```bash
python scripts/load_test_orders.py --base-url http://127.0.0.1:18081 --label "无缓存"
```

## 缓存：Redis 只加速读，PostgreSQL 才是唯一事实来源

配置 `REDIS_URL` 即启用，不配就是「没有缓存」（本地和 CI 都不配，跑得一样）。
设计要点都在 `app/cache.py` 的模块注释里，这里只说结论：

- **只缓存商品读路径**：类目、商品静态骨架（标题/描述/属性/品牌/规格与价格）、
  搜索结果（TTL 600s / 600s / 30s）。
- **库存永不进缓存**：商品详情缓存的是静态骨架，每次请求再用一次轻量查询把实时库存
  盖上去。写进缓存就会出现「页面显示有货、下单提示库存不足」。
- **作废用版本号而不是删 key**：`catalog`（运营改商品才变）与 `dynamic`（下单/评价/调库存
  会变）各一个版本号，写操作 `INCR` 对应版本，旧 key 自然过期 —— 不需要枚举删除。
- **Redis 挂了不影响服务**：连不上/报错都直接走库，连续失败还会熔断 30 秒，
  避免每个请求都卡在连接超时上。启动时也**不依赖** Redis（compose 里是 `service_started`）。
- 命中率可以从运营端看：`GET /shop/admin/cache-stats`（还有 `POST .../reset` 便于压测对比）。

## 并发：不超卖的保证

下单会先 `SELECT ... FOR UPDATE` 锁住涉及的 SKU 行，在锁内校验并扣减，同一个事务提交。

⚠️ **加锁查询必须带 `execution_options(populate_existing=True)`**。原因是前面已经把这些
SKU 读进 Session 的 identity map 了，而 SQLAlchemy 默认不会用查询结果覆盖已加载对象的
属性 —— 那样 `FOR UPDATE` 只锁住了行、拿到的还是旧库存，压测会看到「10 个并发全部下单成功、
库存只减 1」的丢失更新。`tests/test_order_concurrency.py` 就是为这个场景写的（修复前是红的）。

另一种等价思路是改成原子的条件更新：
`UPDATE product_skus SET stock = stock - :q WHERE id = :id AND stock >= :q`，
再判断受影响行数是否为 1。

## 本地开发

如果你本地装了 Python 和 PostgreSQL，也可以直接运行（需先创建 `commerce` 库）：

```bash
uv sync
DATABASE_URL=postgresql+psycopg2://cs:密码@127.0.0.1:5432/commerce \
  uv run python main.py
```

环境变量见 `.env.example`。
