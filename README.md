# 🤖 量化交易系统 - 富途 OpenD + OpenClaw 自动交易方案

## 📋 项目概述

本项目实现了一套**半自动化量化交易系统**，核心架构：

```
富途行情服务器 → OpenD（本地转发）→ 策略脚本（Python）
                                         ↓
                                    openclaw agent
                                         ↓
                               OpenClaw AI 助手（猪猪）
                                         ↓
                                   富途模拟/实盘账户
```

---

## 🏗️ 系统架构

### 组件说明

| 组件 | 作用 |
|------|------|
| **富途 OpenD** | 本地行情转发服务，接收富途服务器推送的实时行情 |
| **策略脚本** | Python 编写，运行量化策略，订阅实时行情，产生交易信号 |
| **OpenClaw (CLI)** | `openclaw agent` 命令接收策略信号，转发给 AI 助手 |
| **OpenClaw AI 助手** | 解析信号，执行下单操作，返回交易结果 |
| **富途模拟/实盘账户** | 执行实际交易 |

### 数据流

```
1. 行情订阅
   富途服务器 ──实时行情──▶ OpenD ──转发──▶ 策略脚本

2. 信号发送
   策略脚本 ──openclaw agent CLI──▶ OpenClaw AI

3. 执行交易
   OpenClaw AI ──富途 SDK──▶ OpenD ──转发──▶ 富途服务器

4. 结果反馈
   执行结果 ──AI 回复──▶ 用户（飞书）
```

---

## 🔧 环境要求

### 已安装组件

- [x] 富途 OpenD (GUI 版) - v10.2.6208
- [x] futu-api SDK - v10.2.6218
- [x] Python 3.9+
- [x] OpenClaw

### Python 依赖

```
futu-api==10.2.6218
backtrader==1.9.78.123
matplotlib==3.9.4
pandas==2.3.3
numpy==2.0.2
```

---

## 📁 项目结构

```
quant-trading-system/
├── README.md
├── backend/
│   ├── api/                     # FastAPI 服务层
│   ├── cli/                     # CLI 入口
│   ├── integrations/            # OpenD / agent 对接层
│   ├── monitoring/              # 持仓监控
│   ├── services/                # 策略管理服务
│   └── strategies/              # 策略信号层与实时运行层
├── backtest/                    # 历史 K 线回测
├── config/
│   └── futu_config.json          # 富途配置
├── frontend/                    # Ant Design 管理页面
└── tests/
    └── test_strategy_example.py # 核心策略与回测测试
```

---

## 🚀 使用方式

### 1. 启动 OpenD

确保 OpenD 已启动并登录：

```bash
open "/Applications/Futu_OpenD.app"
```

### 2. 策略信号发送

策略脚本产生信号后，通过 OpenClaw CLI 发送：

```python
import subprocess
import json
from datetime import datetime

def send_signal(code: str, action: str, price: float, quantity: int, note: str = ""):
    """
    发送交易信号给 OpenClaw AI 助手

    Args:
        code: 股票代码，如 HK.00700, US.AAPL
        action: 交易动作，BUY / SELL
        price: 挂单价格
        quantity: 数量
        note: 备注信息
    """
    message = f"【交易信号】\n股票: {code}\n动作: {action}\n价格: {price}\n数量: {quantity}"
    if note:
        message += f"\n备注: {note}"

    # 调用 OpenClaw CLI 发送信号
    subprocess.run([
        'openclaw', 'agent',
        '--message', message,
        '--channel', 'feishu'
    ])

    # 记录日志
    with open('logs/signals.log', 'a') as f:
        f.write(f"[{datetime.now()}] {action} {code} @ {price} x {quantity}\n")

# 使用示例
send_signal('HK.00700', 'BUY', 400.0, 100, '测试信号')
```

### 3. AI 助手执行

OpenClaw 收到信号后，会：
1. 解析信号内容
2. 确认交易要素（代码、价格、数量）
3. 执行下单（模拟盘无需确认）
4. 返回执行结果

### 4. 启动实时策略

```bash
python3 -m backend.cli.run_strategy --strategy single_position_ma --codes SZ.000001
python3 -m backend.cli.run_strategy --strategy pyramiding_ma --codes SZ.000001 --max-position-per-stock 300
```

### 5. 运行历史回测

回测使用 OpenD 的历史 K 线接口 `request_history_kline(...)` 拉取日线数据，并复用同一套均线策略信号层。

```bash
python3 backtest/run_backtest.py \
  --strategy single_position_ma \
  --codes SZ.000001 \
  --start 2026-03-01 \
  --end 2026-04-07 \
  --short-ma 5 \
  --long-ma 10
```

如需输出详细结果：

```bash
python3 backtest/run_backtest.py \
  --strategy pyramiding_ma \
  --codes SZ.000001 \
  --start 2026-01-01 \
  --end 2026-04-07 \
  --report-file backtest/report.json
```

---

## 📊 策略示例

### 均线交叉策略（示例）

```python
from futu import *
import subprocess

# 策略参数
SHORT_MA = 5   # 短期均线
LONG_MA = 20   # 长期均线
CODE = 'HK.00700'

class MaCrossStrategy:
    def __init__(self):
        self.quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
        self.prices = []
        self.position = 0  # 0=空仓, 1=持仓

    def on_tick(self, tick_data):
        price = tick_data['last_price']
        self.prices.append(price)

        if len(self.prices) < LONG_MA:
            return  # 数据不足

        short_ma = sum(self.prices[-SHORT_MA:]) / SHORT_MA
        long_ma = sum(self.prices[-LONG_MA:]) / LONG_MA

        # 金叉买入
        if short_ma > long_ma and self.position == 0:
            self.send_signal('BUY', price)
            self.position = 1

        # 死叉卖出
        elif short_ma < long_ma and self.position == 1:
            self.send_signal('SELL', price)
            self.position = 0

    def send_signal(self, action, price):
        subprocess.run([
            'openclaw', 'agent',
            '--message', f"【交易信号】{action} {CODE} @ {price}",
            '--channel', 'feishu'
        ])
```

---

## ⚠️ 注意事项

### 安全规则

1. **模拟盘优先**：首次运行务必使用模拟盘
2. **实盘确认**：实盘大额交易需要手动确认
3. **限额设置**：建议设置单笔/单日交易限额
4. **交易解锁**：实盘解锁必须在 OpenD GUI 界面手动操作，禁止通过 SDK 解锁

### 限频规则

| 接口 | 限制 |
|------|------|
| 下单 | 15次/30秒 |
| 订阅 | 100~2000（额度制） |

---

## 🔗 相关链接

- [富途 OpenD API 文档](https://openapi.futunn.com/futu-api-doc/)
- [OpenClaw 文档](https://docs.openclaw.ai/)
- [futu-api PyPI](https://pypi.org/project/futu-api/)

---

## 📝 更新日志

### v0.1.0 (2026-04-02)
- 初始版本
- 完成基础架构设计
- 支持富途行情订阅和信号发送
