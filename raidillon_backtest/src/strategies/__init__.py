"""
strategies/__init__.py - Strategy Framework Package

This package provides the strategy framework for the Raidillon backtest engine.
All strategies inherit from BaseStrategy and implement the standard interface
for entry/exit signal generation.

Available Strategy Types:
- VerticalSpreadStrategy: Debit/credit call and put spreads
- SingleOptionStrategy: Long puts (protective), long calls

Usage:
------
    from src.strategies import create_strategy, StrategyConfig
    
    # Load from YAML config
    config = StrategyConfig.from_yaml('VLO_EARNINGS_CALL_SPREAD', yaml_dict)
    strategy = create_strategy(config)
    
    # Generate signals
    signal = strategy.check_entry(market_snapshot)
    if signal:
        # Process entry signal
        pass
"""

from .base import (
    # Core classes
    BaseStrategy,
    StrategyConfig,
    Signal,
    MarketSnapshot,
    
    # Strategy implementations
    VerticalSpreadStrategy,
    SingleOptionStrategy,
    
    # Factory function
    create_strategy,
    
    # Enums
    SignalType,
    ExitReason,
)

__all__ = [
    'BaseStrategy',
    'StrategyConfig',
    'Signal',
    'MarketSnapshot',
    'VerticalSpreadStrategy',
    'SingleOptionStrategy',
    'create_strategy',
    'SignalType',
    'ExitReason',
]
