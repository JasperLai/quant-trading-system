# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A semi-automated quantitative trading system using Futu OpenD for market data and OpenClaw AI assistant for trade execution. Strategies run as subprocesses, subscribe to real-time quotes via OpenD, and send signals (BUY/SELL) to OpenClaw which executes orders.

## Architecture Overview

```
OpenD → QuoteGateway → QuoteHandler → Signal Layer → SignalSender → OpenClaw Agent
                                        ↓
                              PositionMonitor (stop-loss/take-profit)
                                        ↓
                              SQLite ← ← ← ← ← ← ← ← ← API (FastAPI)
```

### Key Design Principles

- **Strategy runs as subprocess**: Not in FastAPI main process
- **SQLite as cross-process state**: API writes commands, subprocess polls and executes
- **Pure signal layer**: `ma_signal.py` contains no OpenD/log/OpenClaw dependencies - reusable in both live and backtest
- **Separation of concerns**: Signal → Runtime Adapter → Monitoring

## Directory Structure

```
backend/
├── api/
│   └── app.py                      # FastAPI service (start/stop/logs/confirm)
├── cli/
│   └── run_strategy.py             # Subprocess entry point
├── integrations/
│   ├── agent/
│   │   └── signal_sender.py       # OpenClaw signal sending
│   └── futu/
│       └── quote_gateway.py        # OpenD connection/subscription
├── monitoring/
│   └── position_monitor.py         # Stop-loss/take-profit monitoring
├── repositories/
│   ├── runtime_repository.py       # SQLite CRUD operations
│   └── sqlite.py                   # SQLite connection wrapper
├── services/
│   └── strategy_manager.py         # Strategy registry and loading
├── strategies/
│   ├── runtime/
│   │   ├── realtime_runner.py      # Live trading adapter (connects to OpenD)
│   │   ├── single_position.py      # Single position MA strategy
│   │   └── pyramiding.py           # Pyramiding MA strategy
│   └── signals/
│       └── ma_signal.py             # Pure signal logic (shared by live & backtest)
backtest/
├── engine.py                       # Backtest engine
├── portfolio.py                    # Backtest account/positions
├── data_provider.py                # Historical K-line fetching
└── run_backtest.py                 # Backtest CLI
```

## Core Classes

### Signal Layer (Pure Logic)
- **`BaseMaSignal`** (`ma_signal.py`): Abstract base for MA crossover signals
- **`SinglePositionMaSignal`**: Single-position model (no position or pending BUY to buy)
- **`PyramidingMaSignal`**: Allows adding positions within a per-stock limit

Key methods:
- `update_bar(bar_data)`: Update historical price series
- `evaluate_quote(quote_data, position_qty)`: Generate BUY/SELL intent
- `calculate_live_ma(code, price)`: Compute real-time MA using latest quote

### Runtime Adapter
- **`RealtimeMaStrategyRunner`** (`realtime_runner.py`): Connects signal layer to OpenD
  - Subscribes to K_DAY (daily bars) and QUOTE (real-time quotes)
  - Delegates quote callbacks to signal layer
  - Handles BUY/SELL signal → `signal_sender` → OpenClaw

### Position Monitoring
- **`PositionMonitor`** (`position_monitor.py`): Manages confirmed positions
  - Tracks stop-loss (-20%) and take-profit (+30%)
  - Sends SELL signals via `signal_sender` when thresholds are hit

### Repository Layer
- **`RuntimeRepository`** (`runtime_repository.py`): SQLite persistence
  - `strategy_runs`: Running instances
  - `runtime_commands`: Pending control commands (confirm_buy/confirm_sell)
  - `positions`: Current aggregated positions
  - `pending_orders`: Pending BUY/SELL orders
  - `executions`: Execution history

## Commands

```bash
# Run tests
python3 -m unittest -v tests/test_strategy_example.py

# Start FastAPI (from project root)
python3 -m uvicorn backend.app:app --reload --port 8000

# Run live strategy directly
python3 -m backend.cli.run_strategy --strategy single_position_ma --codes SZ.000001 --short-ma 5 --long-ma 20 --order-qty 100

# Run backtest
python3 backtest/run_backtest.py --strategy single_position_ma --codes SZ.000001 --start 2026-03-01 --end 2026-04-07 --short-ma 5 --long-ma 10
```

## API Endpoints

- `GET /api/health` - Health check
- `GET /api/strategies` - List available strategies
- `GET /api/runs` - List running instances
- `POST /api/runs` - Start a new strategy run
- `POST /api/runs/{run_id}/stop` - Stop a run
- `GET /api/runs/{run_id}/logs` - Get logs
- `GET /api/runs/{run_id}/state` - Get positions/pending_orders/executions
- `POST /api/runs/{run_id}/confirm-buy` - Agent confirms BUY execution
- `POST /api/runs/{run_id}/confirm-sell` - Agent confirms SELL execution

## Important Notes

- **OpenD must be running** before starting any strategy (live or backtest)
- Stock codes use prefix format: `HK.`, `SZ.`, `US.` (e.g., `HK.03690`, `SZ.000001`)
- **TEST_MODE**: Check `signal_sender.py` - when `True`, skips actual openclaw calls
- Strategy subprocess polls SQLite for commands (confirm_buy/confirm_sell) from agent
- `PositionMonitor` runs inside strategy subprocess, not FastAPI
- Database: `backend/data/runtime.sqlite3` (runtime data, not committed)
