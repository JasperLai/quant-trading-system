# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A semi-automated quantitative trading system using Futu OpenD for market data and OpenClaw AI assistant for trade execution. Strategies run locally, subscribe to real-time quotes via OpenD, and send signals (BUY only) to OpenClaw which executes orders.

## Commands

```bash
# Run tests
python -m pytest tests/test_strategy_example.py -v

# Run strategy (requires OpenD running first)
python scripts/strategy_example.py
```

## Architecture

### Data Flow
```
Futu Server → OpenD (127.0.0.1:11111) → Strategy Script
                                         ↓
                                    signal_sender
                                         ↓
                               openclaw agent --feishu→ OpenClaw AI → Futu Trading
```

### Role Separation
- **Strategy** (`strategy_example.py`): Subscribes to quotes, computes MA crossovers, emits only BUY signals
- **Position Monitor** (`position_monitor.py`): Tracks positions, emits SELL signals on stop-loss/take-profit triggers
- **Signal Sender** (`signal_sender.py`): Sends signals to OpenClaw via CLI; logs to `logs/signals.log`

### Key Classes
- `MaCrossStrategy`: MA crossover strategy, uses `QuoteHandler` (StockQuoteHandlerBase) for real-time quotes
- `QuoteHandler`: Processes quote push callbacks, calls `strategy.on_quote()`
- `PositionMonitor`: Manages positions, checks stop-loss/take-profit on each tick
- `QuoteHandler` inherits from `StockQuoteHandlerBase` in futu-api

### Quote Callback Behavior
`set_handler()` replaces the previous handler. Strategy uses a single `QuoteHandler` for quotes only (K-line data is fetched via `get_cur_kline()` for initialization, not via push callback).

### Important Notes
- `TEST_MODE = True` in `signal_sender.py` and `position_monitor.py` skips actual openclaw calls
- OpenD must be running and logged in before starting the strategy
- Stock codes use prefix format: `HK.`, `SZ.`, `US.` (e.g., `HK.03690`, `SZ.000001`)
- The system is semi-automated: strategies generate signals, OpenClaw AI confirms and executes trades
