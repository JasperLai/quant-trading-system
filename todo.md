# TODO

## 1. 直连执行模式的风控边界

### 当前现状

- `agent` 模式：
  - 策略子进程只产生交易意图
  - agent 负责二次判断、下单与执行
- `direct` 模式：
  - 策略子进程直接调用 `TradingService.place_order(...)`
  - 会绕过 agent 这一层的事前决策/复核风控

### 风险

- `direct` 模式当前更像“联调快捷模式”
- 不适合直接视为正式交易模式
- 会跳过以下能力：
  - 信号复核
  - 下单前仓位再判断
  - 是否允许下单的统一风控闸门
  - 是否改价/缩量/拒单

### 后续动作

- 增加主进程侧的 `ExecutionRiskService`
- 将 `direct` 模式改为：
  - 子进程发执行请求
  - 主进程先做风控审批
  - 审批通过后再调用 `TradingService`

---

## 2. direct 模式的跨进程通信方案

### 当前现状

- 策略运行在子进程
- `TradingService` / `PositionService` / `guardian` 运行在主进程
- 如果 `direct` 模式要补上主进程风控，就不能再让子进程直接碰 broker

### 结论

- 这是一个明确的跨进程通信问题
- 子进程不能直接调用主进程内存对象

### 推荐方案

- 使用本机 HTTP API 作为 IPC
- 建议链路：

```text
RealtimeRunner (subprocess)
  -> POST /api/executions/submit
  -> ExecutionRiskService
  -> TradingService
  -> OpenD / FUTU
```

### 暂不推荐

- 重新引入数据库命令队列作为主执行通道
- 自定义 pipe / socket / queue

原因：
- 当前已有 FastAPI 服务
- 用本机 HTTP 更简单、可观测、可审计

---

## 3. direct 模式的定位

### 当前定位

- 本机开发
- 模拟盘联调
- 无 agent 场景下跑通完整下单链路

### 后续目标

- 区分：
  - `debug direct`
  - `production direct`

建议：
- `debug direct`：允许当前直连路径，便于联调
- `production direct`：必须经过主进程风控闸门

---

## 4. 订单未成交后的处理

### 当前现状

- 限价单可能长期处于 `SUBMITTED`
- 模拟盘也遵守价格撮合规则，不保证瞬时成交
- 当前系统会保留：
  - `trade_orders`
  - `pending_orders`
- 但缺少主动的“未成交订单管理”

### 已暴露问题

- 日内策略可能已经发出 `SELL`
- 但因价格不够激进，订单长期未成交
- 策略由于已有 `pending SELL`，不会继续重复卖出

### 后续动作

- 增加撤单 API
- 增加订单重挂/改价机制
- 在前端交易明细页展示：
  - 挂单时长
  - 是否 stale
  - 是否建议撤改

---

## 5. 策略状态与执行状态解耦的进一步收敛

### 当前现状

- 子进程负责：
  - 行情接入
  - 策略热状态
  - 产生交易意图
  - 在 `direct` 模式下直接发起下单
- 主进程负责：
  - 订单/成交回报
  - 自动落账
  - 仓位维护

### 后续目标

- 子进程只负责：
  - 信号
  - 执行请求
- 主进程统一负责：
  - 执行审批
  - 下单
  - 订单生命周期
  - 成交落账

这会让架构更一致，也能避免 `direct` 模式形成“绕开主进程风控”的后门。
