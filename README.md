# 电商智能客服 · 对话驱动的交易闭环

用户可以在**同一个对话框里**完成「问规则 → 查订单物流 → 加购下单支付 → 申请售后」，
后台是一套业务闭环完整的电商中台（商品/库存 → 购物车 → 订单状态机 → 支付 → 履约 → 优惠券/积分 → 售后 → 评价 → 运营看板）。

这是一个**作品集 / 课程项目**，但每一条结论都按真实系统的方式做：真机部署、真数据库、
真并发压测、真检索评测，能跑的命令都写在这份文档里且逐条验证过。

## 30 秒看懂

```
                        ┌────────────────────────────────┐
   浏览器 ────────────► │  Caddy（:80/:443，反代 + HTTPS） │
                        │   /api/*   → backend:18082      │
                        │   /shop/*  → ecommerce:18081    │
                        │   /mall/*  → frontend:3000      │
                        │   其余      → frontend:3000      │
                        └────────────────────────────────┘
                              │                    │
                ┌─────────────▼──────┐   ┌─────────▼───────────────┐
                │ 客服 Agent（ws）    │──►│ 电商中台                 │
                │ · TurnPlanner      │HTTP│ (ecommerce-service-     │
                │ · 流程引擎 + 槽位   │   │  backend)               │
                │ · RAG 检索         │   │ · 只读查询接口（兼容旧版）│
                │ · SSE 流式         │   │ · /shop/* 交易接口       │
                └─────────┬──────────┘   │ · 运营管理端 + 看板      │
                          │              └─────────┬───────────────┘
                          └──────────┬─────────────┘
                     ┌───────────────▼────────────────────┐
                     │ PostgreSQL 16 + pgvector           │
                     │   customer_service 库 │ commerce 库 │
                     └────────────────────────────────────┘
```

一句话数据流：**浏览器 → Caddy 按路径分流 → 客服 Agent 决定「办业务还是答知识」→
办业务时经 `ws/utils/shop_client.py` 调中台 → 中台在 PostgreSQL 上跑状态机与规则 → SSE 流式回话**。

## 可量化亮点（每条都能复现）

| 亮点 | 证据 |
| --- | --- |
| **检索质量有闭环**：41 条标注集 + Recall@k/MRR/badcase，改动前后可对比 | Recall@1 **91.7% → 100%**、MRR 0.949 → 1.000（[见下](#rag-检索评测)） |
| **并发正确性**：行锁保证不超卖，并记录了踩到的**丢失更新**根因与修法 | 10 并发抢 3 件 → 恰好 **3 单成功 / 7 单被拒 / 库存 0**（[见下](#并发下单不超卖)） |
| **只读缓存**：Redis 只加速读，**库存永不进缓存**；命中率可观测 | 命中率 **99.0%**，吞吐 350.9 → **435.6 req/s**（[见下](#商品读路径缓存)） |
| **交付链路**：CI 构建 → GHCR → SSH 部署 → **部署后自检**（含检索链路冒烟） | `.github/workflows/deploy.yml`、`deploy/deploy.sh` |
| **测试**：客服端 **115** 个用例、中台 **63** 个用例（跑在**真实 PostgreSQL** 上） | `uv run --locked pytest -q` |

## 目录

- [快速开始](#快速开始)
- [对话能做什么](#对话能做什么)
- [实测数据](#实测数据)：[RAG 检索评测](#rag-检索评测) · [并发下单不超卖](#并发下单不超卖) · [商品读路径缓存](#商品读路径缓存)
- [系统设计](#系统设计)：路由表 · 规则集中 · 两处关键取舍
- [开发与测试](#开发与测试)
- [部署到自己的服务器](#部署到自己的服务器)
- [排障 FAQ](#排障-faq)
- [已知限制](#已知限制)
- [相关文档](#相关文档)

## 快速开始

### Docker（推荐；3 个应用容器 + PostgreSQL + Caddy）

```bash
cp deploy/.env.example deploy/.env
cp deploy/backend.env.example deploy/backend.env
cp deploy/ecommerce.env.example deploy/ecommerce.env
docker compose --env-file deploy/.env up -d --build
```

启动后访问 `http://<主机>`（生产环境把 `SITE_ADDRESS` 设成域名，Caddy 会自动申请 HTTPS 证书）。

- 首次启动**自动建表、补齐新增列、写入演示数据**，不需要手工执行 SQL。
- 中台可用 `SEED_ON_STARTUP=false` 关掉演示数据。
- 生产编排是 `docker-compose.prod.yml`（只有 `image:`，不在服务器上构建 —— 2C2G 的机器构建 Next.js 容易 OOM）。

### 本地开发（不用 Docker）

```bash
# 客服 Agent（:18082）
uv sync && uv run python -m ws.api.main

# 电商中台（:18081，需要一个 commerce 库）
cd ecommerce-service-backend && uv sync
DATABASE_URL=postgresql+psycopg2://cs:密码@127.0.0.1:5432/commerce uv run python main.py

# 前端（:3000；next.config.ts 在 dev 下把 /api/* 与 /shop/* 代理到上面两个后端）
cd frontend && npm install && npm run dev
```

### 演示账号

| 账号 | 会员 | 种子数据 |
| --- | --- | --- |
| `u1001` | PLUS（免运费 + 双倍积分） | 5 笔订单（待发货/待揽收/运输中/已完成/已取消）、2 个地址、满500减50 + 满199享9折 |
| `u1002` | 普通会员 | 2 笔订单、1 个地址、新人满100减10 |
| `u1003` | PLUS | 1 笔订单、1 个地址、新人满100减10 + 满199享9折 |

商品 6 款（iPhone 15 Pro、小米恒温水壶、暖宝宝、Apple Watch S9、美的空气炸锅、罗技 MX Master 3S），共 10 个 SKU。

> 登录用户 → 商城账号的映射规则：用户名形如 `u1001` 直接用，否则回落到
> `COMMERCE_DEFAULT_USER_ID`（默认 `u1001`）。前后端规则必须一致（`ws/utils/shop_client.py`
> 与 `frontend/src/lib/shop.ts`），否则会出现「页面看到的购物车和客服操作的不是同一个」。

## 对话能做什么

| 用户说 | 系统行为 |
| --- | --- |
| 「退款多久到账」「七天无理由的条件」 | RAG 检索知识库（向量 + 字面混合检索）后作答 |
| 「帮我查订单 A20260408002 的物流」 | 「物流查询」流程：收集订单号 → 调中台 → 汇报轨迹 |
| 「我要退货」 | 「申请售后」流程：订单号 → 售后类型 → 原因 → **真实创建售后工单** |
| 「帮我把这个加入购物车」 | 「加购」流程，自动挑一个在售规格 |
| 「下单」「用那张9折券下单」 | 结算购物车、自动抵扣优惠券、生成待付款订单（30 分钟超时自动关单） |
| 「支付」「我收到货了」 | 支付 / 确认收货流程，收货后按会员等级发放积分 |
| 「我有什么券」「我有多少积分」 | 查名下优惠券（含是否可用与原因）与积分等级 |
| 「有没有便宜点的水壶」 | 商品搜索（关键词 + 价格区间 + 排序），带出品牌/评分/销量 |

流程与槽位全部声明在 `ws/config/user_flows.yml`：**新增能力 = 加一个 action + 一条流程**，
不需要改对话引擎（有结构断言守着：action 是否注册、槽位是否声明、`next` 是否指向存在的步骤）。

## 实测数据

> 下面三节的数字都是**本机实测**（同一台开发机、同一个 PostgreSQL 容器），
> 脚本在仓库里，命令可直接复现。小样本数字只代表趋势，不能当生产容量结论。

### RAG 检索评测

**41 条标注集**（直接问法 10 / 口语化改写 19 / 政策条款 7 / 超纲 5），指标 Recall@k、MRR、
超纲拒答率，并自动产出 badcase 清单（期望哪条 / 实际返回哪几条 + 分数）。

```bash
python -m ws.knowledge.eval --sweep                # 离线可复现（不需要库/API，CI 跑这个）
python -m ws.knowledge.eval --backend db --sweep   # 真实 pgvector + 真实 embedding 后端
```

真实 pgvector + pg_trgm 上实测（离线哈希向量；1 条用例 = 2.8pp，样本不大但方向明确）：

| 配置 | Recall@1 | Recall@3 | MRR |
| --- | --- | --- | --- |
| 纯向量 | 91.7% | 100% | 0.949 |
| 混合（similarity），字面分不含别名 | 94.4% | 100% | 0.968 |
| 混合（similarity），字面分含别名 | 97.2% | 100% | 0.986 |
| 混合（**word_similarity**），含别名 ← 现在的默认 | **100%** | 100% | **1.000** |

两个改动都是数据决定的，不是凭感觉：

1. **别名参与字面分**（此前只参与向量化）：Recall@1 +2.8pp；
2. **字面分口径换成 `word_similarity`**：再 +2.8pp —— 短问题 vs 长文档时 `similarity()`
   会被长文档的 trigram 稀释到接近 0，而 `word_similarity()` 看的是问题里的词出现了多少。

评测顺手问出来的问题（这才是它最大的价值）：

- **`min_score=0.05` 形同虚设**：正例 top1 分数 0.21~0.80、超纲问题 0.19~0.35，**两段分布重叠**。
  门槛抬到 0.31 能把超纲拒答率从 20% 提到 80%，代价是 Recall@5 掉到 83% ——
  所以**超纲问题要靠意图识别 + 提示词兜底，光调分数门槛会两头不讨好**。
- `pg_trgm` 缺失时混合检索会**静默退化成纯向量**，现在启动时会兜底创建该扩展并记日志。

### 并发下单不超卖

```bash
python scripts/load_test_orders.py --base-url http://127.0.0.1:18081 --label "无缓存"
```

10 个并发请求抢同一个 SKU 的 3 件库存：

| 指标 | 结果 |
| --- | --- |
| 成功下单 | 3 |
| 因库存不足被拒（HTTP 409） | 7 |
| 最终库存 | 0（绝不为负） |

**这里踩过一个很典型的坑，值得单独记**：代码里本来就有 `SELECT ... FOR UPDATE`，但压测显示
10 个并发**全部下单成功、库存只减了 1**（丢失更新）。根因是 `get_sku_by_code()` 已经把这些
SKU 读进了 SQLAlchemy 的 identity map，而 `with_for_update()` 返回的是**同一个对象、属性不会
被刷新** —— 行锁住了，用的却是旧库存。修法是给三处加锁查询加
`execution_options(populate_existing=True)`。`ecommerce-service-backend/tests/test_order_concurrency.py`
修复前是红的，现在守着这条结论。

另一种等价思路是原子条件更新：
`UPDATE product_skus SET stock = stock - :q WHERE id = :id AND stock >= :q`，再看受影响行数。

### 商品读路径缓存

`REDIS_URL` 配了就启用，不配就是「没有缓存」（本地和 CI 都不配，跑法完全一样）。
PostgreSQL 始终是唯一事实来源，**库存这类强一致字段永远不进缓存** —— 商品详情缓存的只是
「静态骨架」，每次请求再用一次轻量查询把实时库存盖上去，否则会出现「页面显示有货、下单说库存不足」。

同机、20 并发、400 次请求：

| 指标 | 直连 PostgreSQL | 开启 Redis |
| --- | --- | --- |
| 吞吐 | 350.9 req/s | **435.6 req/s** |
| 平均延迟 | 56 ms | 45 ms |
| P50 | 54 ms | 41 ms |
| 缓存命中率 | — | **99.0%**（396/400） |

数据量小的时候绝对收益有限（省掉的是每次请求的 2~3 次 SQL），值钱的是**边界设计**：
作废用版本号（`catalog` / `dynamic` 各一个，写操作 `INCR`，不枚举删 key）、
Redis 挂了自动降级 + 30 秒熔断、命中率可以从 `GET /shop/admin/cache-stats` 读出来。

## 系统设计

### 反向代理路由表（`deploy/Caddyfile`）

| 路径 | 去向 | 说明 |
| --- | --- | --- |
| `/api/*`、`/docs*`、`/openapi.json` | `backend:18082` | 客服 Agent |
| `/shop/*` | `ecommerce:18081` | **中台接口**（含 `/shop/admin/*` 运营端） |
| `/mall/*`、`/cart`、`/orders`、`/me`、`/chat`、`/admin` | `frontend:3000` | 前端页面 |
| 其余 | `frontend:3000` | 兜底 |

⚠️ **接口前缀与页面前缀不能重名**。踩过的坑：中台接口是 `/shop/*`，而商品详情页原本也是
`/shop/[productId]`，点卡片请求 `/shop/SKU10005` 被当成接口发给中台，页面显示
`{"detail":"Not Found"}`；列表页 `/shop`（无斜杠，不匹配 `/shop/*`）却是好的，非常有迷惑性。
现在页面统一在 `/mall/*`，并且有守卫测试：`tests/test_route_namespaces.py`
断言「任何反代前缀都不能与前端页面同名」「页面链接不能指向接口命名空间」。

### 业务规则集中在一处

金额计算、订单与售后状态机、运费（满 99 包邮 / PLUS 免运费 / 否则 8 元）、优惠券、
积分规则全部在 `ecommerce-service-backend/app/shop_rules.py`，是**纯函数、可单测**：

- 订单：待付款 → 待发货 → 待揽收 → 运输中 → 待收货 → 已完成 / 已取消（30 分钟未支付自动关单）
- 售后：提交 → 审核 → 寄回 → 验收 → 退款完成（退货入库会回滚库存）
- 金额一律用 `Numeric` 与字符串传输，前端统一走 `money()` 格式化

### 两处关键取舍

- **不引入 Alembic**：单库、单人维护、部署即启动，迁移框架收益不抵成本；改用幂等的
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` + 幂等补种回填（中台 19 处、知识库 1 处）。
- **Embedding 走 API 而不是自托管**：2C2G 的服务器装不下 torch 类模型，因此用 OpenAI 兼容的
  embeddings 接口；未配置时自动退化为本地词法向量，服务照常可用（有测试守着降级路径）。

## 开发与测试

```
ws/                          客服 Agent
  config/user_flows.yml        流程与槽位声明（交易流程也在这里编排）
  plan/                        本轮计划生成与校验（办理业务 / 咨询知识 / 闲聊）
  task/                        流程引擎、任务状态机、action 注册表
  task/custom/                 业务 action（查订单/物流/推荐 + 交易 9 个）
  knowledge/                   RAG：语料、向量库、意图路由、检索、评测
  utils/shop_client.py         与中台的唯一集成点（用户映射 / URL / 文案）
ecommerce-service-backend/   电商中台（/shop 接口 + 运营端 + 状态机 + 规则）
frontend/                     Next.js 前端（聊天 / 商城 / 购物车 / 订单 / 运营后台）
deploy/                       Caddyfile、各服务 env 模板、bootstrap 与配置下发脚本
scripts/                      e2e 联调、压测、商品封面生成
tests/                        客服端用例 + 部署脚本与 workflow 的断言
```

```bash
# 客服端（115 个用例；含流程 YAML 结构断言、RAG 评测、路由命名空间守卫）
uv run --locked pytest -q

# 中台（63 个用例；集成测试跑在真实 PostgreSQL 上，无库时自动 skip，CI 里 skip 即失败）
cd ecommerce-service-backend && uv run --locked pytest -q

# 前端
cd frontend && npx tsc --noEmit && npm run build

# 跨服务端到端联调（真实服务 + 真实库，可反复执行）
python scripts/e2e_shop_flow.py --base-url http://127.0.0.1:18081 --user u1002
```

CI（`.github/workflows/deploy.yml`）一共 7 个 job：判断改动范围 → 4 个校验
（客服端测试、中台测试、部署脚本与 workflow 断言、前端类型检查与构建）→ **只重建改动过的镜像**
→ 部署。没改动的组件用 `docker buildx imagetools create` 复制 manifest（不传层数据），
服务器拉取时每层都命中本地缓存。

## 部署到自己的服务器

服务器只需要装 Docker，**不需要在服务器上构建**（生产编排只用镜像）。

1. 在 GitHub 仓库配置 Secrets：`SERVER_HOST`、`SERVER_USER`、`SERVER_PORT`、`SERVER_APP_DIR`、
   `SERVER_SSH_KEY`；embedding 相关可选 `EMBEDDING_BASE_URL`、`EMBEDDING_MODEL`、`EMBEDDING_API_KEY`
   （**不要**设 `EMBEDDING_DIM`，维度由模型探测）。
2. push 到 `main`，流水线自动构建 → 推送 GHCR → SSH 部署。
3. 部署脚本自己做完这些事：同步代码 → 下发 Secrets 到 env 文件 → `docker compose pull/up`
   → **重建 Caddy 容器**（bind mount 的 Caddyfile 改了 compose 不会自动重建）→
   **探测 `/shop/categories`**（不通过就重启 Caddy 再探测）→ 打印容器状态。

部署后自检会检查 embedding 后端可用性，并跑一遍检索评测（它同时是检索链路的冒烟测试：
能跑完就说明「建表 → 向量 → SQL 检索」整条链路是通的）。

## 排障 FAQ

**浏览器直接打开 `/shop/xxx` 看到 `{"detail":"Not Found"}`？**
那是**接口**命名空间，不是页面。商城页面在 `/mall`、`/mall/SKU10005`。

**问答答「信息不足」，但商品/订单都能查？**
知识检索链路的问题，按顺序查：
`docker exec cs-backend python -m ws.knowledge.reindex --probe`（embedding 后端是否可用）→
`uv run pytest -q tests/test_knowledge_rag.py`（离线可跑）→
确认数据库有 `pg_trgm` 扩展（缺了会退化成纯向量，启动日志里有一条 warning）→
`docker exec cs-backend python -m ws.knowledge.eval --backend db`（跑通即链路正常）。

**页面能开，但所有接口 404/500？**
看 Caddy 实际加载的配置：`docker exec cs-caddy wget -qO- http://127.0.0.1:2019/config/ | grep -c '/shop'`，
是 0 就 `docker restart cs-caddy`。`caddy reload` 返回 0 **不代表**规则生效（踩过），
所以部署脚本现在直接重建 Caddy 容器。

**服务器拉镜像很慢？**
镜像在 GHCR（境外），国内服务器跨境拉取是主要瓶颈；只重建改动过的镜像已经省掉大部分，
进一步的方案是换到同地域的镜像服务。

## 已知限制

- **运营端未鉴权**：`/shop/admin/*` 目前公开（演示取舍）。生产必须在网关或服务层加访问控制。
- **用户映射靠用户名兜底**：真实系统应做成「账号绑定」表。
- **中台保留两套售后入口**：老接口 `/orders/{id}/refund-applications`（客服早期在用）与新的
  售后工单 `/shop/orders/{id}/after-sales`，前者为兼容保留。
- **数字来自本机小样本**：检索评测 41 条、压测 400 次请求，只代表趋势；换 embedding 模型后
  评测与门槛结论都要重跑。
- **超纲问题拦不住**：分数分布重叠，目前靠意图路由 + 提示词缓解，没有做专门的拒答模型。

## 相关文档

- 中台接口一览、状态机、数据库演进、缓存与并发细节：
  [`ecommerce-service-backend/README.md`](ecommerce-service-backend/README.md)
- 环境变量模板：`deploy/*.env.example`
- 流程编排：`ws/config/user_flows.yml`
- 检索评测集：`ws/knowledge/data/rag_eval.json`（改检索前先看它的 badcase）
