# 电商智能客服（AI Customer Service + 电商中台）

一个**对话驱动交易**的电商智能客服系统：用户既能咨询规则、查订单物流，也能直接
在对话里加购、下单、支付、确认收货、申请售后；后台是一套业务闭环完整的电商中台
（商品/SKU/库存、购物车、订单状态机、支付、履约、优惠券、积分、售后工单、评价、
商品搜索、运营管理端与经营看板）。

- 客服 Agent：FastAPI + LangChain + DeepSeek，YAML 流程引擎 + 槽位收集 + RAG 检索
- 电商中台：FastAPI + SQLAlchemy + PostgreSQL，只读查询接口 + `/shop/*` 交易接口
- 前端：Next.js 16 + React 19 + Tailwind v4，聊天（SSE 打字机）+ 商城 + 运营后台
- 交付：Docker Compose + Caddy 反代 + GitHub Actions（构建 → GHCR → SSH 部署 → 部署后自检）

## 系统架构

```
                        ┌──────────────────────────────┐
   浏览器  ───────────► │  Caddy (:80/:443)            │
                        │   /api/*  → backend:18082    │
                        │   /shop/* → ecommerce:18081  │
                        │   其余    → frontend:3000     │
                        └──────────────────────────────┘
                             │                │
              ┌──────────────▼───┐   ┌────────▼─────────────┐
              │ 客服 Agent        │   │ 电商中台              │
              │ (ws, FastAPI)     │──►│ (ecommerce-service-   │
              │  · TurnPlanner    │HTTP│  backend, FastAPI)   │
              │  · 流程引擎+槽位   │   │  · 只读查询接口        │
              │  · RAG 检索        │   │  · /shop/* 交易接口    │
              │  · SSE 流式        │   │  · 运营管理端 + 看板    │
              └────────┬──────────┘   └────────┬─────────────┘
                       │                       │
              ┌────────▼───────────────────────▼─────────────┐
              │ PostgreSQL 16 + pgvector                      │
              │   customer_service 库 │ commerce 库             │
              └───────────────────────────────────────────────┘
```

## 对话能做什么

| 用户说 | 系统行为 |
| --- | --- |
| 「退款多久到账」「七天无理由的条件」 | RAG 检索知识库（百炼 embedding + pgvector 混合检索）后作答 |
| 「帮我查订单 A20260408002 的物流」 | 走「物流查询」流程，收集订单号 → 调中台 → 汇报轨迹 |
| 「我要退货」 | 走「申请售后」流程：订单号 → 售后类型 → 原因 → 真实创建售后工单 |
| 「帮我把这个加入购物车」 | 走「加购」流程，自动挑一个在售规格并加入购物车 |
| 「下单」「用那张9折券下单」 | 结算购物车、自动抵扣优惠券、生成待付款订单（30 分钟超时自动关单） |
| 「支付」「我收到货了」 | 走支付 / 确认收货流程，收货后按会员等级发放积分 |
| 「我有什么券」「我有多少积分」 | 查询名下优惠券（含是否可用与原因）与积分等级 |
| 「我的待付款订单」 | 按状态筛选订单列表 |
| 「有没有便宜点的水壶」 | 商品搜索（关键词 + 价格区间 + 排序），带出品牌/评分/销量 |

## 核心能力

### 客服 Agent（`ws/`）

- **两层决策**：`TurnPlanner` 产出本轮计划（办理业务 / 咨询知识 / 闲聊三选一），
  `TurnPlanValidation` 校验计划与聚焦对象，避免乱开流程。
- **流程引擎**：`user_flows.yml` 声明流程与槽位，支持 `start / collect / action /
  response / end` 与条件跳转；槽位可从消息、聚焦对象或 action 结果填充。
- **任务状态机**：任务可暂停/恢复/取消/切换，状态持久化在 PostgreSQL，
  服务重启不丢上下文。
- **知识检索**：意图路由到 FAQ / RAG / 中台 API 三类 provider；向量 + 关键词
  混合检索，embedding 可插拔（未配置自动退化为本地词法向量）。
- **对话体验**：SSE 逐字流式输出、历史摘要压缩、清晰澄清（缺槽位/多意图）。

### 电商中台（`ecommerce-service-backend/`）

| 域 | 能力 |
| --- | --- |
| 商品 | 类目、品牌、SKU 多规格、库存、上下架、评分与销量聚合、关键词/价格/排序搜索 |
| 交易 | 购物车增删改查与勾选、结算预览（算钱 + 校验库存/券/地址）、下单、Mock 支付、发货、收货 |
| 履约 | 物流单与轨迹、状态机推进（待揽收 → 运输中 → 待收货） |
| 营销 | 满减券/折扣券、领取与限领、下单占用与取消归还、积分与会员权益 |
| 售后 | 仅退款/退货退款工单状态机（提交 → 审核 → 寄回 → 验收 → 退款），退货入库回滚库存 |
| 评价 | 已完成订单评价、追评、商家回复、商品评分聚合、评价奖励积分 |
| 运营 | 订单管理与发货、售后审核台、库存调整与低库存预警、优惠券管理与定向发券、经营看板（GMV/状态分布/售后率/热销榜） |

所有金额计算、状态机、运费与积分规则集中在 `app/shop_rules.py`（纯函数、可单测）。

## 快速开始

### Docker（推荐）

```bash
cp deploy/.env.example deploy/.env
cp deploy/backend.env.example deploy/backend.env
cp deploy/ecommerce.env.example deploy/ecommerce.env
docker compose --env-file deploy/.env up -d --build
```

首次启动自动建表、补齐新增列并写入演示数据（中台可用 `SEED_ON_STARTUP=false` 关闭）。
访问 `http://<主机>`（生产由 Caddy 按域名申请 HTTPS 证书）。

### 本地开发

```bash
# 客服 Agent
uv sync
uv run python -m ws.api.main                      # :18082

# 电商中台
cd ecommerce-service-backend && uv sync
DATABASE_URL=postgresql+psycopg2://cs:密码@127.0.0.1:5432/commerce uv run python main.py   # :18081

# 前端（next.config.ts 已把 /api/* 与 /shop/* 代理到本地两个后端）
cd frontend && npm install && npm run dev          # :3000
```

### 演示账号

| 账号 | 会员 | 种子数据 |
| --- | --- | --- |
| `u1001` | PLUS（免运费 + 双倍积分） | 5 笔订单（待发货/待揽收/运输中/已完成/已取消）、2 个地址、满500减50 + 满199享9折 |
| `u1002` | 普通会员 | 2 笔订单、1 个地址、新人满100减10 |
| `u1003` | PLUS | 1 笔订单、1 个地址、新人满100减10 + 满199享9折 |

商品 6 款（iPhone 15 Pro、小米电热水壶、暖宝宝、Apple Watch S9、美的空气炸锅、
罗技 MX Master 3S），共 10 个 SKU。

## RAG 检索评测（有实测数字）

`ws/knowledge/eval.py` 把检索质量变成可对比的表：**41 条评测集**（直接问法 10 / 口语化改写 19 /
政策条款 7 / 超纲 5），指标 Recall@k、MRR、超纲拒答率，并自动产出 badcase 清单。

```bash
python -m ws.knowledge.eval --sweep                # 离线可复现（不需要库/API，CI 用这个）
python -m ws.knowledge.eval --backend db --sweep   # 真实 pgvector + 真实 embedding 后端
```

真实 pgvector + pg_trgm 上实测（用离线哈希向量；1 条用例 = 2.8pp，样本不大但方向明确）：

| 配置 | Recall@1 | Recall@3 | MRR |
| --- | --- | --- | --- |
| 纯向量 | 91.7% | 100% | 0.949 |
| 混合（similarity），字面分**不含**别名 | 94.4% | 100% | 0.968 |
| 混合（similarity），字面分**含**别名 | 97.2% | 100% | 0.986 |
| 混合（**word_similarity**），含别名 ← 现在的默认 | **100%** | 100% | **1.000** |

两个由数据决定（而不是凭感觉）的改动：

1. **别名参与字面分**（此前只参与向量化）：Recall@1 +2.8pp；
2. **字面分口径换成 `word_similarity`**：再 +2.8pp —— 短问题 vs 长文档时 `similarity()`
   会被长文档的 trigram 稀释得接近 0，而 `word_similarity()` 看的是问题里的词在文档中出现多少。

评测顺手问出来的问题（这才是它最大的价值）：

- **`min_score=0.05` 形同虚设**：正例 top1 分数 0.21~0.80、超纲问题 0.19~0.35，**两段分布重叠**。
  门槛抬到 0.31 可把超纲拒答率从 20% 提到 80%，代价是 Recall@5 掉到 83% ——
  所以**超纲问题必须靠意图识别 + 提示词兜底，光调分数门槛会两头不讨好**。
- `pg_trgm` 缺失时混合检索会**静默退化成纯向量**（现在启动时会兜底创建该扩展并记录日志）。
- badcase 清单会自动打印「期望哪条 / 实际返回哪几条（含分数）」，改检索前先看它。

## 并发与性能（有实测数字）

### 并发下单：行锁保证不超卖

10 个并发请求抢同一个 SKU 的 3 件库存（`scripts/load_test_orders.py`）：

| 指标 | 结果 |
| --- | --- |
| 成功下单 | 3 |
| 因库存不足被拒（HTTP 409） | 7 |
| 最终库存 | 0（绝不为负） |

**这里踩过一个很典型的坑，值得单独记下来**：代码里本来就有 `SELECT ... FOR UPDATE`，
但压测显示 10 个并发**全部下单成功、库存只减了 1** —— 典型的丢失更新。
根因是 `get_sku_by_code()` 已经把这些 SKU 读进了 SQLAlchemy 的 identity map，
而 `with_for_update()` 返回的是**同一个对象、属性不会被刷新**：行锁住了，用的却是旧库存。
修法是给加锁查询加 `execution_options(populate_existing=True)`，强制用锁内读到的值覆盖。
`tests/test_order_concurrency.py`（修复前会红）与压测脚本现在守着这条结论。

### 商品读路径：可选 Redis 缓存

PostgreSQL 始终是唯一事实来源，Redis 只加速读；**库存这类强一致字段永远不进缓存**
（否则会出现「页面显示有货、下单却提示库存不足」）。同机、20 并发、400 次请求：

| 指标 | 直连 PostgreSQL | 开启 Redis 缓存 |
| --- | --- | --- |
| 吞吐 | 350.9 req/s | 435.6 req/s |
| 平均延迟 | 56 ms | 45 ms |
| P50 | 54 ms | 41 ms |
| 缓存命中率 | — | 99.0%（396/400） |

数据量小的时候收益有限（省掉的是每次请求的 2~3 次 SQL），但命中率与延迟的趋势是明确的；
而且**开启缓存后「并发不超卖」的结论不变**。复现步骤见中台 README。

## 测试与验证

```bash
uv run --locked pytest -q                       # 客服 Agent：113 个用例
cd ecommerce-service-backend && uv run --locked pytest -q   # 中台：63 个用例（19 规则 + 44 真库集成）
cd frontend && npx tsc --noEmit && npm run build
```

- 中台集成测试跑在**真实 PostgreSQL** 上（库存行锁、Numeric 金额、JSON 列在 SQLite
  上验证不了）；CI 里由 `services: postgres` 提供，并且**有测试被 skip 就让 CI 红**。
- 客服侧的流程 YAML 有**结构断言**：action 是否注册、槽位是否声明、`next` 是否
  指向存在的步骤、模板里的 `{{ slots.x }}` 是否存在 —— 这些错了原本要等到运行时才炸。
- 跨服务端到端联调（真实服务 + 真实库）：

```bash
python scripts/e2e_shop_flow.py --base-url http://127.0.0.1:18081 --user u1002
```

- 压测（商品读路径吞吐/分位延迟 + 并发抢购是否超卖）：

```bash
python scripts/load_test_orders.py --base-url http://127.0.0.1:18081 --label "无缓存"
```

## 目录结构

```
ws/                          客服 Agent
  config/user_flows.yml        流程与槽位声明（交易流程也在这里编排）
  plan/                        本轮计划生成与校验
  task/                        流程引擎、任务状态机、action 注册表
  task/custom/                 业务 action（查订单/物流/推荐 + 交易 9 个）
  knowledge/                   RAG：语料、向量库、意图路由、检索
  utils/shop_client.py         与中台的唯一集成点（用户映射/URL/文案）
ecommerce-service-backend/   电商中台
  app/shop_rules.py            订单与售后状态机、运费、优惠券、积分（纯函数）
  app/shop_service.py          交易核心：购物车/下单/支付/收货/取消
  app/admin_service.py         运营端：履约、库存、发券、看板
  app/shop_api.py 等           /shop 路由（交易、售后评价、运营端）
  tests/                       规则单测 + 真库集成测试
frontend/                     Next.js 前端（聊天 + 商城 + 运营后台）
deploy/                       Caddyfile、各服务 env 模板、部署与配置下发脚本
scripts/e2e_shop_flow.py      跨服务端到端联调脚本
.github/workflows/deploy.yml  CI/CD：6 个 job，构建 → 推送 → SSH 部署 → 部署后自检
```

## 设计取舍与已知限制

- **不引入 Alembic**：单库、单人维护、部署即启动，迁移框架收益不抵成本；
  改用幂等的 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` + 幂等补种回填。
- **运营端接口未鉴权**：`/shop/admin/*` 目前公开（演示取舍）。生产必须在网关
  （`deploy/Caddyfile` 里的 `@shop` 规则）或服务层加访问控制。
- **用户映射**：登录用户 → 商城账号由 `COMMERCE_DEFAULT_USER_ID` 兜底（默认 `u1001`）；
  真实系统应做成「账号绑定」表。前端 `commerceUserId()` 与后端规则保持一致，
  否则会出现「页面看到的购物车与客服操作的不是同一个」。
- **Embedding 走 API 而不是自托管**：2C2G 的服务器装不下 torch 类模型，
  因此用 OpenAI 兼容的 embeddings 接口，未配置时自动退化为本地词法向量。
- **中台保留两套售后入口**：老接口 `/orders/{id}/refund-applications`（客服 Agent
  早期在用）与新的售后工单 `/shop/orders/{id}/after-sales`；前者为兼容保留。

## 相关文档

- 电商中台接口、状态机、迁移策略与联调方式：[`ecommerce-service-backend/README.md`](ecommerce-service-backend/README.md)
- 环境变量模板：`deploy/*.env.example`
- 流程编排：`ws/config/user_flows.yml`（新增能力只需加一个 action + 一条流程）
