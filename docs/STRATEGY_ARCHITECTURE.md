# 策略管理与运行架构设计

## 1. 文档范围

本文档描述当前代码库中的策略管理、实时运行、信号发送、持仓监控与回测复用设计。

文档基于以下实现文件：

- `/Users/mubinlai/code/quant-trading-system/backend/services/strategy_manager.py`
- `/Users/mubinlai/code/quant-trading-system/backend/strategies/signals/ma_signal.py`
- `/Users/mubinlai/code/quant-trading-system/backend/strategies/runtime/realtime_runner.py`
- `/Users/mubinlai/code/quant-trading-system/backend/integrations/agent/signal_sender.py`
- `/Users/mubinlai/code/quant-trading-system/backend/monitoring/position_monitor.py`
- `/Users/mubinlai/code/quant-trading-system/backend/api/app.py`

本文档描述的是当前实现，不是理想化方案。

## 2. 设计目标

当前设计主要解决三个问题：

1. 将 API 接入、策略判断、信号发送拆开，避免强耦合。
2. 让同一套策略逻辑既能用于实时运行，也能用于历史回测。
3. 将“发出交易意图”和“成交后登记持仓”分离，避免未成交单被误记为持仓。
4. 将运行状态、持仓和待确认命令落到 SQLite，避免关键状态只存在进程内存。

## 3. 总体架构

```mermaid
flowchart LR
    UI["AntD Frontend"] --> API["FastAPI Strategy Service"]
    API --> SM["StrategyManager"]
    API --> REPO["SQLite Runtime Repository"]
    SM --> RT["Realtime Strategy Runner"]
    RT --> OD["Futu OpenD / OpenQuoteContext"]
    RT --> SG["MA Signal"]
    RT --> SS["Signal Sender"]
    RT --> PM["Position Monitor"]
    RT --> REPO
    SS --> OC["openclaw agent"]
    PM --> OC
```

## 4. 模块职责

### 4.1 StrategyManager

文件：
- `/Users/mubinlai/code/quant-trading-system/backend/services/strategy_manager.py`

职责：

1. 注册可用策略。
2. 管理策略元数据。
3. 根据策略名和参数创建实时策略实例。
4. 根据策略名和参数创建纯信号实例。

核心设计：

- `STRATEGY_REGISTRY` 同时注册两类实现：
  - `runtime_class`
  - `signal_class`
- `STRATEGY_METADATA` 用于前端展示和默认参数管理。

当前已注册策略：

- `single_position_ma`
- `pyramiding_ma`

### 4.2 纯信号层

文件：
- `/Users/mubinlai/code/quant-trading-system/backend/strategies/signals/ma_signal.py`

职责：

1. 维护历史 K 线收盘价样本。
2. 根据 `time_key` 去重并更新样本。
3. 计算短期/长期 MA。
4. 根据持仓模型判断是否产生 BUY / SELL 信号。

不负责：

1. OpenD 连接。
2. 行情订阅。
3. OpenClaw 调用。
4. 持仓登记和止损止盈执行。

核心状态：

- `prices[code]`：历史收盘价样本。
- `bar_time_keys[code]`：用于按 `time_key` 去重。
- `last_short_ma / last_long_ma`：上次参考均线值。
- `pending_buys`：待确认买单状态。
- `pending_sells`：待确认卖单状态。

### 4.3 实时运行适配层

文件：
- `/Users/mubinlai/code/quant-trading-system/backend/strategies/runtime/realtime_runner.py`

职责：

1. 连接 OpenD。
2. 订阅日 K 和实时报价。
3. 初始化历史日线数据。
4. 将报价回调转成对纯信号层的调用。
5. 将 BUY / SELL 信号转交给 agent 对接层。
6. 将成交确认后的持仓交给 `position_monitor`。

这里是策略与外部世界之间的桥接层。

### 4.4 Signal Sender

文件：
- `/Users/mubinlai/code/quant-trading-system/backend/integrations/agent/signal_sender.py`

职责：

1. 统一构造交易信号消息。
2. 调用 `openclaw agent`。
3. 记录发送日志。

它不关心均线策略细节，只关心收到一个标准化交易信号后如何发送。

### 4.5 Position Monitor

文件：
- `/Users/mubinlai/code/quant-trading-system/backend/monitoring/position_monitor.py`

职责：

1. 保存已成交持仓。
2. 支持累计加仓后的加权均价。
3. 在行情更新时检查止损/止盈。
4. 触发极端风险时发送兜底 SELL 信号。

它不负责决定正常的策略性买卖，只负责为已成交仓位提供固定 `-20%` 止损和 `+30%` 止盈兜底。

### 4.6 后台服务

文件：
- `/Users/mubinlai/code/quant-trading-system/backend/app.py`

职责：

1. 提供策略列表接口。
2. 提供启动和停止策略接口。
3. 以子进程方式托管策略运行。
4. 收集并暴露日志。

后台服务不在主进程里直接执行策略逻辑，而是通过 `subprocess.Popen` 启动策略脚本。

### 4.7 Repository 层

文件：
- `/Users/mubinlai/code/quant-trading-system/backend/repositories/runtime_repository.py`
- `/Users/mubinlai/code/quant-trading-system/backend/repositories/sqlite.py`

职责：

1. 持久化 `strategy_runs`。
2. 持久化 `runtime_commands`。
3. 持久化 `positions`。
4. 持久化 `pending_orders`。
5. 为 API 和策略子进程提供共享状态源。

当前 SQLite 不是可选辅助层，而是运行状态的共享仓储层。

## 5. API 接入设计

实时行情接入全部集中在：

- `/Users/mubinlai/code/quant-trading-system/backend/strategies/runtime/realtime_runner.py`

当前主要使用了以下 Futu OpenD API：

### 5.1 建立行情上下文

通过：

```python
OpenQuoteContext(host=host, port=port)
```

建立本地到 OpenD 的连接。

### 5.2 注册报价回调

通过：

```python
quote_ctx.set_handler(self.quote_handler)
```

注册 `StockQuoteHandlerBase` 子类。

收到推送后，`QuoteHandler.on_recv_rsp()` 会把每条报价继续传给：

```python
self.strategy.on_quote(quote)
```

### 5.3 订阅数据

当前实时策略启动时会做两类订阅：

1. `SubType.K_DAY`
   - 用途：保证可以初始化日线数据。
   - 设置为 `subscribe_push=False`，不依赖日 K 推送驱动策略。

2. `SubType.QUOTE`
   - 用途：持续接收报价回调。
   - 实时策略的盘中判断依赖这个推送。

### 5.4 初始化历史日线

启动后调用：

```python
get_cur_kline(code, long_ma_period + 5, KLType.K_DAY)
```

用途：

1. 获取足够的历史日线样本。
2. 构建初始 `prices` 序列。
3. 刷新短期/长期 MA 基准值。

### 5.5 实时计算方式

当前策略不是分钟 K 驱动，而是：

1. 用历史日线作为 MA 样本基础。
2. 用最新 `QUOTE.last_price` 替换最后一根日线的收盘价。
3. 计算盘中的“实时短期 MA / 实时长期 MA”。

这样实现的是：

- `日线 MA + QUOTE 实时判断`

而不是：

- `分钟 K 策略`

### 5.6 运行状态持久化

运行时状态目前采用“进程内热状态 + SQLite 持久化快照”的模式。

SQLite 中有 4 张核心表：

1. `strategy_runs`
   - 记录 `run_id`、策略名、参数、PID、状态、日志路径
2. `runtime_commands`
   - 记录 agent 回调写入的成交确认命令
3. `positions`
   - 记录策略子进程同步出的已确认持仓
4. `pending_orders`
   - 记录待确认的 BUY / SELL

设计意图是：

- API 不直接改写策略子进程内存
- API 负责写数据库命令
- 策略子进程轮询数据库命令并处理
- 策略子进程把最新持仓和 pending 状态再同步回数据库

这样 API 可以直接从数据库查询状态，而不是依赖活跃子进程的内存对象。

## 6. 策略实现设计

### 6.1 数据更新

纯信号层通过 `update_bar(bar_data)` 维护样本。

去重规则：

1. 如果 `time_key` 不同，追加一条新 bar。
2. 如果 `time_key` 相同，更新最后一条价格。

这样避免了以前按 `close_price` 去重带来的错误。

### 6.2 实时报价评估

纯信号层通过 `evaluate_quote(quote_data, position_qty)` 评估交易意图。

核心流程：

1. 样本不足长期均线周期时，不评估。
2. 计算实时短期/长期 MA。
3. 用 `last_short_ma / last_long_ma` 与当前值比较。
4. 满足金叉条件产生 BUY 意图，满足死叉条件产生 SELL 意图。

当前核心判定为：

```python
if prev_short_ma <= prev_long_ma and short_ma > long_ma:
    action = 'BUY'
elif prev_short_ma >= prev_long_ma and short_ma < long_ma:
    action = 'SELL'
```

这意味着当前策略是“事件驱动的金叉买入 / 死叉卖出”，不是“只要当前均线状态满足就立即交易”。

### 6.3 两种仓位模型

#### 单仓模型

类：
- `SinglePositionMaSignal`

规则：

1. 同一标的同一时间只允许一笔正式持仓。
2. 同一标的只允许一个 pending BUY。

#### 有上限加仓模型

类：
- `PyramidingMaSignal`

规则：

1. 允许继续 BUY。
2. 但 `当前已持仓数量 + 待确认数量 + 本次买入数量` 不能超过上限。

## 7. 信号发送与持仓监控解耦

这是当前设计的核心。

### 7.1 解耦前的问题

如果策略在发出 BUY 时立刻登记持仓，会出现：

1. 订单未成交却被当作持仓。
2. 成交失败后风控状态错误。
3. 执行层与策略层强耦合。

### 7.2 当前解耦方式

当前 BUY / SELL 链路分成三段：

1. `MA Signal`
   - 判断是否应当发 BUY 或 SELL。

2. `Realtime Runner`
   - 负责把交易意图转换为一次发送动作。
   - 同时把标的记为 `pending buy` 或 `pending sell`。

3. 外部执行回报
   - 成交后再调用 `confirm_position(...)`。
   - 这时才进入 `PositionMonitor`。

因此：

- BUY / SELL 信号都不等于已经成交。
- 持仓状态以成交确认结果为准。

### 7.3 策略信号流程

```mermaid
sequenceDiagram
    participant Q as Quote Callback
    participant RT as Realtime Runner
    participant SG as MA Signal
    participant SS as Signal Sender
    participant AG as Agent
    participant PM as Position Monitor

    Q->>RT: on_quote(quote)
    RT->>SG: evaluate_quote(quote, position_qty)
    SG-->>RT: action / qty
    alt 触发金叉
        RT->>SS: send_signal(BUY)
        SS->>AG: openclaw agent
        RT->>SG: add_pending_buy(code, qty)
        AG-->>RT: 成交确认
        RT->>SG: clear_pending_buy(code, qty)
        RT->>PM: confirm_position(...)
    else 触发死叉
        RT->>SS: send_signal(SELL)
        SS->>AG: openclaw agent
        RT->>SG: add_pending_sell(code, qty)
        AG-->>RT: 成交确认
        RT->>SG: clear_pending_sell(code, qty)
        RT->>PM: remove_position(...)
    end
```

### 7.4 SELL 流程

SELL 有两类来源：

1. 策略型 SELL
   - 例如均线死叉卖出

2. 风控型 SELL
   - 例如 `PositionMonitor` 的固定 `-20%` 止损和 `+30%` 止盈

流程：

1. 报价进入 `Realtime Runner`
2. `Realtime Runner` 调用 `monitor.on_tick(code, price)`
3. 如果触发固定止损或止盈
4. `PositionMonitor` 发送兜底 SELL 信号
5. 持仓从监控器中移除

这意味着：

- 策略负责正常买卖观点
- `PositionMonitor` 负责极端风险兜底

## 8. 实时运行时序图

```mermaid
sequenceDiagram
    participant UI as Frontend/API
    participant SM as StrategyManager
    participant RT as RealtimeRunner
    participant OD as OpenD
    participant SG as MASignal
    participant SS as SignalSender
    participant AG as Agent/OpenClaw
    participant PM as PositionMonitor

    UI->>SM: start_strategy(name, params)
    SM->>RT: create runtime instance
    RT->>OD: OpenQuoteContext()
    RT->>OD: subscribe(K_DAY, push=false)
    RT->>OD: subscribe(QUOTE, push=true)
    RT->>OD: get_cur_kline()
    OD-->>RT: historical daily bars
    RT->>SG: update_bar(bar)
    RT->>SG: refresh_reference_ma()

    loop QUOTE 推送
        OD-->>RT: QuoteHandler.on_recv_rsp(quote)
        RT->>SG: evaluate_quote(quote, position_qty)
        SG-->>RT: action?/ma values
        alt 新金叉
            RT->>SS: send_signal(BUY)
            SS->>AG: openclaw agent
        else 新死叉
            RT->>SS: send_signal(SELL)
            SS->>AG: openclaw agent
        end
        RT->>PM: on_tick(code, price)
        alt 触发固定止损/止盈
            PM->>AG: send SELL signal
        end
    end
```

## 9. 启动流程图

```mermaid
flowchart TD
    A["启动策略"] --> B["StrategyManager 解析策略名和参数"]
    B --> C["创建 Realtime Runner"]
    C --> D["连接 OpenD"]
    D --> E["订阅 K_DAY"]
    E --> F["订阅 QUOTE"]
    F --> G["拉取历史日线"]
    G --> H["喂给 MA Signal 建样本"]
    H --> I["刷新短期/长期 MA 基线"]
    I --> J["进入 QUOTE 事件循环"]
    J --> K["实时计算 MA"]
    K --> L{"是否产生新金叉/死叉?"}
    L -- 否 --> M["继续等待报价"]
    L -- 金叉 --> N["调用 Agent 对接层发 BUY"]
    L -- 死叉 --> O["调用 Agent 对接层发 SELL"]
    N --> P["进入 pending buy 状态"]
    O --> Q["进入 pending sell 状态"]
    P --> M
    Q --> M
```

## 10. 后台服务运行模型

后台服务使用子进程托管策略，不把策略主循环直接塞进 FastAPI 线程。

原因：

1. 长循环策略与 Web 请求生命周期不同。
2. 子进程隔离后，单个策略崩溃不会直接影响 API 服务。
3. 日志可以天然按运行实例落到单独文件。

当前实现方式：

1. `POST /api/runs`
2. 构造 `python3 -m backend.cli.run_strategy ...`
3. 用 `subprocess.Popen(...)` 启动
4. 输出重定向到 `backend/logs/<run_id>.log`
5. 前端通过日志接口读取尾部内容

## 11. 当前设计的优点

### 11.1 策略复用性更好

实时与回测共享 `signal_class`，避免重复写一套均线逻辑。

### 11.2 OpenD 依赖边界清晰

OpenD 相关代码集中在 `Realtime Runner`，不会污染策略判断层。

### 11.3 发送通道可替换

如果未来不再使用 `openclaw agent`，只需要替换 agent 对接层实现。

### 11.4 成交与持仓状态一致

当前设计避免了“发 BUY 即登记仓位”的错误状态。

## 12. 当前局限

目前仍有这些限制：

1. `confirm_position(...)` 还未接入正式的成交回报链路，需要外部调用。
2. `PositionMonitor` 仍是进程内存状态，没有持久化。
3. agent 对接层仍保留 `TEST_MODE`。
4. 启动后如果已经是多头状态，不会补发 BUY，因为当前采用的是“新金叉事件”模型。
5. 回测与实时虽然共用信号层，但执行与持仓模型仍可以继续抽象。

## 13. 后续建议

建议的下一步演进方向：

1. 增加正式的成交确认回调接口，将 `confirm_position(...)` 接入后台服务。
2. 将持仓、pending、运行参数持久化。
3. 继续扩展 agent 对接层为统一执行网关接口。
4. 把实时数据接入层继续抽象为 `MarketDataAdapter`，为未来替换行情源做准备。
