# atguigu ecommerce service

这是一个配套 `atguigu` 项目使用的电商业务服务示例。

它提供：

- 用户最近订单 / 商品
- 订单状态查询
- 物流查询
- 商品信息查询
- 发货提醒创建
- 退款申请创建

初始化数据覆盖了多种典型状态，便于课堂演示：

- 待发货
- 待揽收
- 运输中
- 已完成
- 已取消
- 已有退款申请
- 已有发货提醒

## 启动方式

本项目已并入仓库根目录的 `docker-compose.yml`，与客服 Agent 共用同一个
PostgreSQL 实例（pgvector 镜像），只是使用不同的库：

| 库名 | 使用者 |
| --- | --- |
| `customer_service` | 客服 Agent（对话状态、用户） |
| `commerce` | 本服务（用户、商品、订单、物流） |

在仓库根目录统一启动：

```bash
cd /opt/customer_service
cp deploy/.env.example deploy/.env
cp deploy/backend.env.example deploy/backend.env
cp deploy/ecommerce.env.example deploy/ecommerce.env
docker compose --env-file deploy/.env up -d --build
```

首次启动时本服务会自动建表并写入课程演示数据（可用 `SEED_ON_STARTUP=false` 关闭）。

如果修改过表结构、需要重建数据，清掉数据卷再启动即可：

```bash
docker compose --env-file deploy/.env down -v
docker compose --env-file deploy/.env up -d --build
```

启动后默认地址：

- API: `http://127.0.0.1:18081`
- OpenAPI: `http://127.0.0.1:18081/docs`

## 核心接口

- `GET /health`
- `GET /users/{user_id}/orders`
- `GET /users/{user_id}/products`
- `GET /orders/{order_id}`
- `GET /orders/{order_id}/status`
- `GET /orders/{order_id}/logistics`
- `GET /products/{product_id}`
- `POST /orders/{order_id}/shipping-reminders`
- `POST /orders/{order_id}/refund-applications`

## 本地开发

如果你本地装了 Python 和 PostgreSQL，也可以直接运行（需先创建 `commerce` 库）：

```bash
uv sync
DATABASE_URL=postgresql+psycopg2://cs:密码@127.0.0.1:5432/commerce \
  uv run python main.py
```

环境变量见 `.env.example`。
