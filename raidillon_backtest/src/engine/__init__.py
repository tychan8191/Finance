"""
engine/__init__.py - Backtest Engine Package

This package provides the core backtesting infrastructure:
- Portfolio: Position and P&L management
- BacktestEngine: Main simulation orchestrator
- DataManager: Market data loading and access

Usage:
------
    from src.engine import BacktestEngine, Portfolio, Position
    
    # Run a backtest from YAML
    engine = BacktestEngine.from_yaml('config/strategies.yaml', variant='base')
    results = engine.run()
    
    # Or use Portfolio directly for custom simulations
    portfolio = Portfolio(initial_cash=10000)
    position = Position.create_spread(...)
    portfolio.open_position(position)
"""

from .portfolio import (
    Portfolio,
    Position,
    Leg,
    PositionSide,
    OptionRight,
    PositionStatus,
)

from .backtest import (
    BacktestEngine,
    BacktestConfig,
    DataManager,
    SimpleOptionsPricer,
)

__all__ = [
    # Portfolio management
    'Portfolio',
    'Position',
    'Leg',
    'PositionSide',
    'OptionRight',
    'PositionStatus',
    
    # Backtest engine
    'BacktestEngine',
    'BacktestConfig',
    'DataManager',
    'SimpleOptionsPricer',
]
