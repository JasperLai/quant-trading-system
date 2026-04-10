# Agent 对接接口文档

## 1. 文档目标

本文档面向负责执行交易的 agent。

目标：

1. 查询可用策略
2. 启动策略实例
3. 读取运行状态、日志和数据库快照
4. 通过后端交易接口下单

## 2. 基本说明

### 2.1 Base URL

本地开发环境通常为：

```text
http://127.0.0.1:8000
```

### 2.2 数据格式

- 请求体：`application/json`
- 响应体：JSON

### 2.3 核心概念

#### 策略信号

策略发出的 `BUY` / `SELL` 只是交易意图，不等于成交。

#### 成交确认

当 agent 通过后端交易接口下单时，不需要再手动调用确认接口。

当前实现中，后端会优先基于 OpenD 交易推送回报自动更新 SQLite；若推送暂时缺失，则由后台订单同步作为兜底。

自动落账会同时更新：

- `trade_orders`
- `trade_deals`
- `strategy_positions`
- `account_positions`
- `pending_orders`
- `executions`

#### 交易信号协议

策略或 guardian 发给 agent 的消息中，会携带一段 `signal_payload=...` JSON。

agent 应按其中的 `execution` 字段执行：

- `execution`
  表示应该调用的下单 API 和对应 payload

要求：

1. 不要直接绕过后端调用 FUTU API
2. 直接调用 `execution.api` 下单
3. 成交确认由后端基于 broker 订单/成交回报自动完成，不需要手工再调 confirm 接口

#### run_id

每次启动策略都会生成唯一 `run_id`。

后续日志读取、停止策略、状态查询都依赖它。

## 3. 接口总览

| 方法 | 路径 | 用途 |
|------|------|------|
| `GET` | `/api/health` | 健康检查 |
| `GET` | `/api/strategies` | 获取可用策略列表 |
| `GET` | `/api/runs` | 获取策略运行列表 |
| `POST` | `/api/runs` | 启动策略 |
| `POST` | `/api/runs/{run_id}/stop` | 停止策略 |
| `GET` | `/api/runs/{run_id}/logs` | 获取策略日志 |
| `GET` | `/api/runs/{run_id}/state` | 获取数据库状态快照 |
| `POST` | `/api/trading/orders` | 下单接口（agent 主入口） |
| `GET` | `/api/trading/orders` | 查询订单 |
| `POST` | `/api/runs/{run_id}/confirm-buy` | 手工补录买入成交 |
| `POST` | `/api/runs/{run_id}/confirm-sell` | 手工补录卖出成交 |
| `POST` | `/api/accounts/{account_id}/confirm-sell` | 手工补录账户级卖出成交 |

## 4. 健康检查

```http
GET /api/health
```

响应：

```json
{
  "status": "ok"
}
```

## 5. 获取可用策略

```http
GET /api/strategies
```

响应示例：

```json
[
  {
    "name": "single_position_ma",
    "title": "单仓均线策略",
    "description": "单标的同一时间只允许一笔正式持仓。",
    "params": {
      "codes": ["SZ.000001"],
      "short_ma": 5,
      "long_ma": 20,
      "order_qty": 100
    }
  }
]
```

## 6. 启动策略

```http
POST /api/runs
Content-Type: application/json
```

请求体字段：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `strategyName` | string | 是 | 策略名 |
| `codes` | string[] | 否 | 标的列表 |
| `shortMa` | integer | 否 | 短期均线周期 |
| `longMa` | integer | 否 | 长期均线周期 |
| `orderQty` | integer | 否 | 单次下单数量 |
| `maxPositionPerStock` | integer | 否 | 加仓策略单标的最大仓位 |

请求示例：

```json
{
  "strategyName": "pyramiding_ma",
  "codes": ["HK.03690"],
  "shortMa": 5,
  "longMa": 20,
  "orderQty": 100,
  "maxPositionPerStock": 300
}
```

响应示例：

```json
{
  "id": "44feca50",
  "strategyName": "pyramiding_ma",
  "status": "running"
}
```

## 7. 获取运行列表

```http
GET /api/runs
```

## 8. 获取日志

```http
GET /api/runs/{run_id}/logs?lines=200
```

响应示例：

```json
{
  "lines": [
    "启动策略: pyramiding_ma_cross",
    "[QUOTE回调] HK.03690 2026-04-08 09:47:24 last=85.25 volume=19092986"
  ]
}
```

## 9. 获取数据库状态快照

```http
GET /api/runs/{run_id}/state
```

用途：

- 查询该策略实例的归属持仓
- 查询账户级聚合持仓
- 查询待确认订单
- 查询成交流水

响应示例：

```json
{
  "run": {
    "id": "44feca50",
    "strategyName": "pyramiding_ma",
    "status": "running"
  },
  "positions": [
    {
      "run_id": "44feca50",
      "code": "HK.03690",
      "qty": 100,
      "entry": 85.2
    }
  ],
  "strategyPositions": [
    {
      "run_id": "44feca50",
      "code": "HK.03690",
      "qty": 100,
      "entry": 85.2
    }
  ],
  "accountPositions": [
    {
      "account_id": "default",
      "code": "HK.03690",
      "qty": 300,
      "entry": 84.7
    }
  ],
  "pendingOrders": [
    {
      "run_id": "44feca50",
      "code": "HK.03690",
      "side": "SELL",
      "qty": 100
    }
  ],
  "executions": [
    {
      "run_id": "44feca50",
      "code": "HK.03690",
      "side": "BUY",
      "qty": 100,
      "price": 85.2
    }
  ]
}
```

说明：

- `positions` 是兼容字段，当前等价于 `strategyPositions`
- `accountPositions` 是账户级总仓位视图

## 10. 停止策略

```http
POST /api/runs/{run_id}/stop
```

停止策略只会停止该策略子进程，不会清空数据库中的已确认持仓。账户级仓位仍由 `PositionGuardian` 继续监控。

## 11. 手工补录买入成交

默认情况下，agent 不应调用本接口。

仅当以下场景出现时才使用：
- broker 实际已成交，但自动结算链路未能正常落账
- 需要手工补录历史成交
- 调试或运维补偿

```http
POST /api/runs/{run_id}/confirm-buy
Content-Type: application/json
```

请求字段：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `code` | string | 是 | 标的代码 |
| `qty` | integer | 是 | 成交数量 |
| `entryPrice` | number | 是 | 买入均价 |
| `stopLoss` | number | 否 | 自定义止损价 |
| `takeProfit` | number | 否 | 自定义止盈价 |
| `reason` | string | 否 | 原因说明 |

请求示例：

```json
{
  "code": "HK.03690",
  "qty": 100,
  "entryPrice": 85.2,
  "reason": "agent成交确认"
}
```

响应示例：

```json
{
  "status": "applied",
  "runId": "44feca50",
  "position": {
    "qty": 100,
    "entry": 85.2,
    "stop": 68.16,
    "profit": 110.76
  }
}
```

## 12. 手工补录卖出成交

默认情况下，agent 不应调用本接口。

仅用于自动结算失败后的人工补偿。

```http
POST /api/runs/{run_id}/confirm-sell
Content-Type: application/json
```

请求字段：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `code` | string | 是 | 标的代码 |
| `qty` | integer | 否 | 卖出数量；为空表示按当前策略归属仓位全量卖出 |
| `exitPrice` | number | 否 | 卖出均价 |
| `reason` | string | 否 | 原因说明 |

请求示例：

```json
{
  "code": "HK.03690",
  "qty": 100,
  "exitPrice": 91.5,
  "reason": "agent卖出成交确认"
}
```

响应示例：

```json
{
  "status": "applied",
  "runId": "44feca50",
  "remainingQty": 0
}
```

## 13. 推荐调用流程

1. `GET /api/strategies`
2. `POST /api/runs`
3. 记住 `run_id`
4. 轮询：
   - `GET /api/runs/{run_id}/logs`
   - `GET /api/runs/{run_id}/state`
5. 收到策略或 guardian 信号后，只调用 `signal_payload.execution.api`
6. 下单后等待后端基于 broker 订单/成交回报自动落账
7. 只有自动结算失败时，才使用手工补录接口

## 14. 当前实现说明

1. 策略子进程不再消费成交确认命令。
2. 子进程只依赖数据库中的 `strategy_positions` 和 `pending_orders` 恢复运行态。
3. `PositionGuardian` 基于 `account_positions` 做账户级固定止损止盈兜底。
4. guardian 风控卖出不绑定单一 `run_id`，应使用账户级确认接口。

## 15. 手工补录账户级卖出成交

默认情况下，agent 不应调用本接口。

当账户级自动结算失败，且需要对 guardian 卖出做人工补录时，使用本接口。

```http
POST /api/accounts/{account_id}/confirm-sell
Content-Type: application/json
```

请求示例：

```json
{
  "code": "HK.03690",
  "qty": 300,
  "exitPrice": 91.5,
  "reason": "guardian stop sell"
}
```

响应示例：

```json
{
  "status": "applied",
  "accountId": "default",
  "remainingQty": 0,
  "allocations": [
    {
      "run_id": "run-a",
      "qty": 100,
      "remainingQty": 0
    },
    {
      "run_id": "run-b",
      "qty": 200,
      "remainingQty": 0
    }
  ]
}
```

分摊规则：

- 当前按 `strategy_positions` 的 `entry_time / updated_at / run_id` 顺序分摊
- 可以理解为“先进入的策略归属仓位先扣减”
