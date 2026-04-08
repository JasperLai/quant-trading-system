#!/usr/bin/env python3
"""实时策略 CLI 入口。"""

from backend.services.strategy_manager import StrategyManager, build_strategy_kwargs, parse_args


def main():
    args = parse_args()
    manager = StrategyManager()
    manager.start_strategy(args.strategy, **build_strategy_kwargs(args))


if __name__ == '__main__':
    main()
