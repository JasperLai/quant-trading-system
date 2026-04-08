# Agent 对接接口文档

## 1. 文档目标

本文档面向负责执行交易的 agent。

目标是让 agent 能基于当前后端服务完成以下动作：

1. 查询可用策略
2. 启动一个策略运行实例
3. 查询运行状态、日志与数据库快照
4. 在买入成交后确认持仓
5. 在卖出成交后确认退出

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

策略会发出：

- `BUY`
- `SELL`

它们都只是交易意图，不等于成交结果。

#### 成交确认

agent 真正完成买卖后，需要显式回调后端：

- 买入成交后调用 `confirm-buy`
- 卖出成交后调用 `confirm-sell`

后端收到确认后，不是直接写子进程内存，而是先写入 SQLite 中的 `runtime_commands` 表。策略子进程会轮询命令表，处理后更新 `positions` 和 `pending_orders`。
每次成交确认被处理后，还会新增一条 `executions` 成交流水。

#### run_id

每次启动策略都会生成唯一的 `run_id`。

后续日志读取、停止运行、成交确认、状态查询都需要它。

## 3. 接口总览

| 方法 | 路径 | 用途 |
|------|------|------|
| `GET` | `/api/health` | 健康检查 |
| `GET` | `/api/strategies` | 获取可用策略列表 |
| `GET` | `/api/runs` | 获取策略运行列表 |
| `POST` | `/api/runs` | 启动策略 |
| `POST` | `/api/runs/{run_id}/stop` | 停止策略 |
| `GET` | `/api/runs/{run_id}/logs` | 获取策略日志 |
| `GET` | `/api/runs/{run_id}/state` | 获取数据库中的运行状态快照 |
| `POST` | `/api/runs/{run_id}/confirm-buy` | 买入成交确认 |
| `POST` | `/api/runs/{run_id}/confirm-sell` | 卖出成交确认 |

## 4. 健康检查

### 4.1 请求

```http
GET /api/health
```

### 4.2 响应

```json
{
  "status": "ok"
}
```

## 5. 获取可用策略

### 5.1 请求

```http
GET /api/strategies
```

### 5.2 响应示例

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
  },
  {
    "name": "pyramiding_ma",
    "title": "有上限加仓均线策略",
    "description": "允许在仓位上限内继续加仓，并把待确认买单数量纳入仓位计算。",
    "params": {
      "codes": ["SZ.000001"],
      "short_ma": 5,
      "long_ma": 20,
      "order_qty": 100,
      "max_position_per_stock": 300
    }
  }
]
```

## 6. 启动策略

### 6.1 请求

```http
POST /api/runs
Content-Type: application/json
```

### 6.2 请求体字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `strategyName` | string | 是 | 策略名，如 `single_position_ma` |
| `codes` | string[] | 否 | 标的列表 |
| `shortMa` | integer | 否 | 短期均线周期 |
| `longMa` | integer | 否 | 长期均线周期 |
| `orderQty` | integer | 否 | 单次下单数量 |
| `maxPositionPerStock` | integer | 否 | 加仓策略的单标的最大仓位 |

### 6.3 请求示例

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

### 6.4 响应示例

```json
{
  "id": "44feca50",
  "strategyName": "pyramiding_ma",
  "config": {
    "strategy": "pyramiding_ma",
    "codes": ["HK.03690"],
    "short_ma": 5,
    "long_ma": 20,
    "order_qty": 100,
    "max_position_per_stock": 300,
    "run_id": "44feca50",
    "db_path": "/Users/mubinlai/code/quant-trading-system/backend/data/runtime.sqlite3"
  },
  "pid": 8499,
  "status": "running",
  "createdAt": 1775612844.659,
  "stoppedAt": null,
  "logPath": "/Users/mubinlai/code/quant-trading-system/backend/logs/44feca50.log"
}
```

### 6.5 关键说明

agent 启动后必须保存返回的 `id`，后续所有确认接口都需要它。

## 7. 获取运行列表

### 7.1 请求

```http
GET /api/runs
```

### 7.2 响应示例

```json
[
  {
    "id": "44feca50",
    "strategyName": "pyramiding_ma",
    "config": {
      "strategy": "pyramiding_ma",
      "codes": ["HK.03690"],
      "short_ma": 5,
      "long_ma": 20,
      "order_qty": 100,
      "max_position_per_stock": 300,
      "run_id": "44feca50",
      "db_path": "/Users/mubinlai/code/quant-trading-system/backend/data/runtime.sqlite3"
    },
    "pid": 8499,
    "status": "running",
    "createdAt": 1775612844.659,
    "stoppedAt": null,
    "logPath": "/Users/mubinlai/code/quant-trading-system/backend/logs/44feca50.log"
  }
]
```

## 8. 获取日志

### 8.1 请求

```http
GET /api/runs/{run_id}/logs?lines=200
```

### 8.2 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `run_id` | string | 是 | 运行实例 ID |
| `lines` | integer | 否 | 返回最后 N 行日志，默认 `200` |

### 8.3 响应示例

```json
{
  "lines": [
    "启动策略: pyramiding_ma_cross",
    "代码: HK.03690",
    "短期MA(5)=82.92, 长期MA(20)=80.95",
    "[QUOTE回调] HK.03690 2026-04-08 09:47:24 last=85.25 volume=19092986",
    "[报价] HK.03690 实时价: 85.25 | 短期MA(5): 82.92 | 长期MA(20): 80.95"
  ]
}
```

## 9. 获取数据库状态快照

### 9.1 请求

```http
GET /api/runs/{run_id}/state
```

### 9.2 用途

这个接口直接从 SQLite 读取运行状态，不依赖策略子进程内存。适合 agent 做对账、恢复和状态校验。

### 9.3 响应示例

```json
{
  "run": {
    "id": "44feca50",
    "strategyName": "pyramiding_ma",
    "config": {
      "strategy": "pyramiding_ma",
      "codes": ["HK.03690"],
      "short_ma": 5,
      "long_ma": 20,
      "order_qty": 100,
      "max_position_per_stock": 300,
      "run_id": "44feca50",
      "db_path": "/Users/mubinlai/code/quant-trading-system/backend/data/runtime.sqlite3"
    },
    "pid": 8499,
    "status": "running",
    "createdAt": 1775612844.659,
    "stoppedAt": null,
    "logPath": "/Users/mubinlai/code/quant-trading-system/backend/logs/44feca50.log"
  },
  "positions": [
    {
      "run_id": "44feca50",
      "code": "HK.03690",
      "qty": 100,
      "entry": 85.2,
      "stop": 68.16,
      "profit": 110.76,
      "stop_pct": -0.2,
      "profit_pct": 0.3,
      "reason": "均线金叉买入",
      "entry_time": "2026-04-08T09:50:01.000000",
      "updated_at": 1775613001.0
    }
  ],
  "pendingOrders": [
    {
      "run_id": "44feca50",
      "code": "HK.03690",
      "side": "SELL",
      "qty": 100,
      "updated_at": 1775613200.0
    }
  ],
  "executions": [
    {
      "id": 1,
      "run_id": "44feca50",
      "code": "HK.03690",
      "side": "BUY",
      "qty": 100,
      "price": 85.2,
      "reason": "agent成交确认",
      "position_qty_after": 100,
      "avg_entry_after": 85.2,
      "realized_pnl": null,
      "metadata": null,
      "executed_at": 1775613001.0
    }
  ]
}
```

## 10. 停止策略

### 10.1 请求

```http
POST /api/runs/{run_id}/stop
```

### 10.2 响应示例

```json
{
  "id": "44feca50",
  "strategyName": "pyramiding_ma",
  "status": "stopped"
}
```

## 11. 买入成交确认

### 11.1 请求

```http
POST /api/runs/{run_id}/confirm-buy
Content-Type: application/json
```

### 11.2 请求体字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `code` | string | 是 | 标的代码 |
| `qty` | integer | 是 | 成交数量 |
| `entryPrice` | number | 是 | 成交均价 |
| `stopLoss` | number | 否 | 自定义止损价 |
| `takeProfit` | number | 否 | 自定义止盈价 |
| `reason` | string | 否 | 成交原因说明 |

### 11.3 请求示例

```json
{
  "code": "HK.03690",
  "qty": 100,
  "entryPrice": 85.2,
  "reason": "agent成交确认"
}
```

### 11.4 响应示例

```json
{
  "status": "queued",
  "runId": "44feca50",
  "command": {
    "action": "confirm_buy",
    "code": "HK.03690",
    "qty": 100,
    "entry_price": 85.2,
    "stop_loss": null,
    "take_profit": null,
    "reason": "agent成交确认"
  }
}
```

### 11.5 处理语义

这个接口只负责把成交确认写入 SQLite 命令表，不保证策略子进程在同一瞬间完成处理。策略子进程会在轮询周期内消费这条命令，并更新持仓表与成交流水表。

## 12. 卖出成交确认

### 12.1 请求

```http
POST /api/runs/{run_id}/confirm-sell
Content-Type: application/json
```

### 12.2 请求体字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `code` | string | 是 | 标的代码 |
| `qty` | integer | 否 | 成交数量 |
| `exitPrice` | number | 否 | 卖出成交价，建议传入以便记录成交流水和已实现盈亏 |
| `reason` | string | 否 | 成交原因说明 |

### 12.3 请求示例

```json
{
  "code": "HK.03690",
  "qty": 100,
  "exitPrice": 91.5,
  "reason": "agent卖出成交确认"
}
```

### 12.4 响应示例

```json
{
  "status": "queued",
  "runId": "44feca50",
  "command": {
    "action": "confirm_sell",
    "code": "HK.03690",
    "qty": 100,
    "exit_price": 91.5,
    "reason": "agent卖出成交确认"
  }
}
```

## 13. agent 推荐调用流程

推荐按照下面顺序使用：

1. `GET /api/strategies`
2. `POST /api/runs`
3. 记住返回的 `run_id`
4. 持续轮询：
   - `GET /api/runs/{run_id}/logs`
   - `GET /api/runs/{run_id}/state`
5. 当收到策略 `BUY` 意图并实际买入成功：
   - 调 `POST /api/runs/{run_id}/confirm-buy`
6. 当收到策略 `SELL` 意图或 monitor 风控卖出并实际卖出成功：
   - 调 `POST /api/runs/{run_id}/confirm-sell`

## 14. 当前实现限制

- 当前命令处理是“API 写 SQLite，策略子进程轮询 SQLite”，不是同步 RPC。
- `/api/runs/{run_id}/state` 读取的是持久化快照，适合做状态核对，但可能比进程内瞬时状态有轻微延迟。
- 如果 agent 只执行交易而不回调确认接口，数据库中的持仓状态不会更新，monitor 也不会被激活或解除。
