#!/usr/bin/env python3
"""Position persistence and confirmation service."""

from datetime import datetime

from backend.core.config import DEFAULT_ACCOUNT_ID, STOP_LOSS_PCT, TAKE_PROFIT_PCT
from backend.repositories.runtime_repository import RuntimeRepository


class PositionService:
    def __init__(self, repository: RuntimeRepository):
        self.repository = repository
        self.account_id = DEFAULT_ACCOUNT_ID

    def _consume_pending_order(self, run_id, code, side, filled_qty):
        pending = self.repository.get_pending_order(run_id, code, side)
        if pending is None:
            return

        remaining_qty = round(float(pending['qty']) - float(filled_qty), 6)
        if remaining_qty > 0:
            self.repository.upsert_pending_order(run_id, code, side, remaining_qty, commit=False)
        else:
            self.repository.remove_pending_order(run_id, code, side, commit=False)

    def confirm_position(
        self,
        run_id,
        code,
        qty,
        entry_price,
        stop_loss=None,
        take_profit=None,
        reason='均线金叉买入',
    ):
        with self.repository.transaction():
            existing = self.repository.get_strategy_position(run_id, code)
            if existing is None:
                total_qty = qty
                avg_entry = entry_price
                entry_time = datetime.now().isoformat()
            else:
                total_qty = existing['qty'] + qty
                avg_entry = round((existing['entry'] * existing['qty'] + entry_price * qty) / total_qty, 4)
                entry_time = existing.get('entry_time') or datetime.now().isoformat()

            position = {
                'qty': total_qty,
                'entry': avg_entry,
                'stop': stop_loss if stop_loss is not None else round(avg_entry * (1 + STOP_LOSS_PCT), 2),
                'profit': take_profit if take_profit is not None else round(avg_entry * (1 + TAKE_PROFIT_PCT), 2),
                'stop_pct': STOP_LOSS_PCT,
                'profit_pct': TAKE_PROFIT_PCT,
                'reason': reason,
                'entry_time': entry_time,
            }
            self.repository.upsert_strategy_position(run_id, code, position, commit=False)
            self._apply_account_buy(code, qty, entry_price, commit=False)
            self._consume_pending_order(run_id, code, 'BUY', qty)
            self.repository.record_execution(
                run_id=run_id,
                code=code,
                side='BUY',
                qty=qty,
                price=entry_price,
                reason=reason,
                position_qty_after=total_qty,
                avg_entry_after=avg_entry,
                commit=False,
            )
            return position

    def confirm_exit(self, run_id, code, qty=None, exit_price=None, reason='均线死叉卖出'):
        with self.repository.transaction():
            existing = self.repository.get_strategy_position(run_id, code)
            if existing is None:
                if qty is not None:
                    self._consume_pending_order(run_id, code, 'SELL', qty)
                else:
                    self.repository.remove_pending_order(run_id, code, 'SELL', commit=False)
                return None

            exit_qty = qty if qty is not None else existing['qty']
            remaining_qty = max(existing['qty'] - exit_qty, 0)
            realized_pnl = None
            if exit_price is not None:
                realized_pnl = round((exit_price - existing['entry']) * exit_qty, 4)

            if remaining_qty > 0:
                updated_position = {
                    'qty': remaining_qty,
                    'entry': existing['entry'],
                    'stop': existing['stop'],
                    'profit': existing['profit'],
                    'stop_pct': existing['stop_pct'],
                    'profit_pct': existing['profit_pct'],
                    'reason': existing.get('reason'),
                    'entry_time': existing.get('entry_time'),
                }
                self.repository.upsert_strategy_position(run_id, code, updated_position, commit=False)
                position_qty_after = remaining_qty
                avg_entry_after = existing['entry']
            else:
                self.repository.delete_strategy_position(run_id, code, commit=False)
                position_qty_after = 0
                avg_entry_after = None

            self._apply_account_sell(code, exit_qty, exit_price, commit=False)

            self._consume_pending_order(run_id, code, 'SELL', exit_qty)
            self.repository.record_execution(
                run_id=run_id,
                code=code,
                side='SELL',
                qty=exit_qty,
                price=exit_price,
                reason=reason,
                position_qty_after=position_qty_after,
                avg_entry_after=avg_entry_after,
                realized_pnl=realized_pnl,
                metadata={'position_entry': existing['entry']},
                commit=False,
            )
            return position_qty_after

    def confirm_account_exit(self, code, qty=None, exit_price=None, reason='固定风控卖出', account_id=None):
        account_id = account_id or self.account_id
        with self.repository.transaction():
            account_position = self.repository.get_account_position(account_id, code)
            if account_position is None:
                return {'remainingQty': None, 'allocations': []}

            exit_qty = qty if qty is not None else account_position['qty']
            exit_qty = min(exit_qty, account_position['qty'])
            remaining_to_allocate = exit_qty
            allocations = []

            strategy_positions = self.repository.list_strategy_positions_by_code(code)
            for position in strategy_positions:
                if remaining_to_allocate <= 0:
                    break

                allocated_qty = min(position['qty'], remaining_to_allocate)
                remaining_qty = position['qty'] - allocated_qty
                realized_pnl = None
                if exit_price is not None:
                    realized_pnl = round((exit_price - position['entry']) * allocated_qty, 4)

                if remaining_qty > 0:
                    updated_position = {
                        'qty': remaining_qty,
                        'entry': position['entry'],
                        'stop': position['stop'],
                        'profit': position['profit'],
                        'stop_pct': position['stop_pct'],
                        'profit_pct': position['profit_pct'],
                        'reason': position.get('reason'),
                        'entry_time': position.get('entry_time'),
                    }
                    self.repository.upsert_strategy_position(position['run_id'], code, updated_position, commit=False)
                    position_qty_after = remaining_qty
                    avg_entry_after = position['entry']
                else:
                    self.repository.delete_strategy_position(position['run_id'], code, commit=False)
                    position_qty_after = 0
                    avg_entry_after = None

                self._consume_pending_order(position['run_id'], code, 'SELL', allocated_qty)
                self.repository.record_execution(
                    run_id=position['run_id'],
                    code=code,
                    side='SELL',
                    qty=allocated_qty,
                    price=exit_price,
                    reason=reason,
                    position_qty_after=position_qty_after,
                    avg_entry_after=avg_entry_after,
                    realized_pnl=realized_pnl,
                    metadata={
                        'source': 'account_guardian',
                        'account_id': account_id,
                        'position_entry': position['entry'],
                    },
                    commit=False,
                )
                allocations.append(
                    {
                        'run_id': position['run_id'],
                        'qty': allocated_qty,
                        'remainingQty': position_qty_after,
                    }
                )
                remaining_to_allocate -= allocated_qty

            applied_exit_qty = exit_qty - remaining_to_allocate
            self._apply_account_sell(code, applied_exit_qty, exit_price, commit=False)

            remaining_account = self.repository.get_account_position(account_id, code)
            return {
                'remainingQty': remaining_account['qty'] if remaining_account else 0,
                'allocations': allocations,
            }

    def _apply_account_buy(self, code, qty, entry_price, commit=True):
        existing = self.repository.get_account_position(self.account_id, code)
        if existing is None:
            total_qty = qty
            avg_entry = entry_price
        else:
            total_qty = existing['qty'] + qty
            avg_entry = round((existing['entry'] * existing['qty'] + entry_price * qty) / total_qty, 4)

        position = {
            'qty': total_qty,
            'entry': avg_entry,
            'stop': round(avg_entry * (1 + STOP_LOSS_PCT), 2),
            'profit': round(avg_entry * (1 + TAKE_PROFIT_PCT), 2),
            'stop_pct': STOP_LOSS_PCT,
            'profit_pct': TAKE_PROFIT_PCT,
        }
        self.repository.upsert_account_position(self.account_id, code, position, commit=commit)

    def _apply_account_sell(self, code, qty, exit_price=None, commit=True):
        existing = self.repository.get_account_position(self.account_id, code)
        if existing is None:
            return
        remaining_qty = max(existing['qty'] - qty, 0)
        if remaining_qty == 0:
            self.repository.delete_account_position(self.account_id, code, commit=commit)
            return

        position = {
            'qty': remaining_qty,
            'entry': existing['entry'],
            'stop': existing['stop'],
            'profit': existing['profit'],
            'stop_pct': existing['stop_pct'],
            'profit_pct': existing['profit_pct'],
        }
        self.repository.upsert_account_position(self.account_id, code, position, commit=commit)
