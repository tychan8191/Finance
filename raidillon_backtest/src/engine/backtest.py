"""
engine/backtest.py - Main Backtest Orchestrator for Raidillon Framework

This module implements the core backtesting engine that coordinates all components:
- Loads and validates market data
- Steps through time bar-by-bar
- Calls strategies for entry/exit signals
- Manages positions through the Portfolio class
- Tracks performance metrics and generates reports

Architecture Overview:
---------------------
The engine follows an event-driven simulation approach:

1. INITIALIZATION
   - Load configuration from strategies.yaml
   - Load market data (equities, VIX, options, calendar)
   - Instantiate all enabled strategies
   - Initialize Portfolio with starting capital

2. SIMULATION LOOP (for each trading day)
   - Build MarketSnapshot from current data
   - For each strategy without open position: check_entry()
   - For each strategy with open position: check_exit()
   - Process signals through Portfolio
   - Mark positions to market
   - Record metrics
   - Check circuit breakers

3. FINALIZATION
   - Close any remaining positions
   - Generate performance report
   - Export trade log and NAV history

Thread Safety: This engine is single-threaded by design. Options backtesting
involves complex state management that doesn't parallelize cleanly.
"""

import os
import sys
import yaml
import logging
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass, field
import pandas as pd
import numpy as np
from collections import defaultdict
import warnings

# Import internal modules
from ..strategies.base import (
    BaseStrategy, StrategyConfig, Signal, SignalType, ExitReason,
    MarketSnapshot, create_strategy, VerticalSpreadStrategy, SingleOptionStrategy
)
from .portfolio import Portfolio, Position, Leg, OptionRight, PositionStatus

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('raidillon.backtest')


# =============================================================================
# PROJECT PATHS
# =============================================================================

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_RAW = PROJECT_ROOT / 'data' / 'raw'
DATA_PROCESSED = PROJECT_ROOT / 'data' / 'processed'
CONFIG_DIR = PROJECT_ROOT / 'config'
OUTPUTS_DIR = PROJECT_ROOT / 'outputs'


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class BacktestConfig:
    """
    Configuration for a backtest run.
    
    This consolidates all settings that control backtest behavior:
    - Date range
    - Portfolio variant (conservative/base/aggressive)
    - Risk limits
    - Execution assumptions
    """
    start_date: date
    end_date: date
    initial_capital: float = 10000.0
    variant: str = 'base'  # conservative, base, aggressive
    
    # Commission and fees
    commission_per_contract: float = 0.65
    assignment_fee: float = 5.00
    
    # Execution assumptions
    slippage_pct: float = 0.01  # 1% slippage on entry/exit
    fill_at_mid: bool = True    # Use mid price vs bid/ask
    
    # Risk limits (pulled from strategies.yaml based on variant)
    max_position_loss_pct: float = 0.04
    max_aggregate_premium_pct: float = 0.20
    max_single_theme_pct: float = 0.25
    min_cash_reserve_pct: float = 0.30
    circuit_breaker_weekly_drawdown: float = 0.05
    
    # Output options
    verbose: bool = True
    save_results: bool = True
    output_dir: Optional[Path] = None
    
    def __post_init__(self):
        if self.output_dir is None:
            self.output_dir = OUTPUTS_DIR
        self.output_dir = Path(self.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    @classmethod
    def from_yaml(
        cls, 
        yaml_config: Dict, 
        variant: str = 'base',
        start_date: str = '2026-01-21',
        end_date: str = '2026-02-28'
    ) -> 'BacktestConfig':
        """Create BacktestConfig from parsed strategies.yaml."""
        
        global_config = yaml_config.get('global', {})
        risk_limits = yaml_config.get('risk_limits', {}).get(variant, {})
        
        return cls(
            start_date=datetime.strptime(start_date, '%Y-%m-%d').date(),
            end_date=datetime.strptime(end_date, '%Y-%m-%d').date(),
            initial_capital=global_config.get('base_nav', 10000),
            variant=variant,
            commission_per_contract=global_config.get('commission_per_contract', 0.65),
            assignment_fee=global_config.get('assignment_fee', 5.00),
            max_position_loss_pct=risk_limits.get('max_position_loss_pct', 0.04),
            max_aggregate_premium_pct=risk_limits.get('max_aggregate_premium_pct', 0.20),
            max_single_theme_pct=risk_limits.get('max_single_theme_pct', 0.25),
            min_cash_reserve_pct=risk_limits.get('min_cash_reserve_pct', 0.30),
            circuit_breaker_weekly_drawdown=risk_limits.get('circuit_breaker_weekly_drawdown', 0.05),
        )


# =============================================================================
# DATA MANAGER
# =============================================================================

class DataManager:
    """
    Manages all market data for the backtest.
    
    Responsibilities:
    - Load and validate CSVs from data/raw/
    - Provide point-in-time data access (no lookahead bias)
    - Build MarketSnapshot objects for each simulation step
    - Cache data for efficient repeated access
    """
    
    def __init__(self, data_dir: Path = DATA_RAW):
        self.data_dir = Path(data_dir)
        
        # Data storage
        self.equities_df: Optional[pd.DataFrame] = None
        self.vix_df: Optional[pd.DataFrame] = None
        self.rates_df: Optional[pd.DataFrame] = None
        self.options_df: Optional[pd.DataFrame] = None
        self.calendar_df: Optional[pd.DataFrame] = None
        self.crack_df: Optional[pd.DataFrame] = None
        self.cftc_df: Optional[pd.DataFrame] = None
        self.vix_futures_df: Optional[pd.DataFrame] = None
        
        # Index for fast lookup
        self._price_cache: Dict[Tuple[str, date], float] = {}
        self._calendar_by_date: Dict[date, List[Dict]] = defaultdict(list)
        
        # Track available date range
        self.min_date: Optional[date] = None
        self.max_date: Optional[date] = None
        
    def load_all(self) -> bool:
        """
        Load all available data files.
        
        Returns:
            True if core data loaded successfully, False otherwise
        """
        success = True
        
        # Load equities (required)
        equities_path = self.data_dir / 'equities_ohlcv.csv'
        if equities_path.exists():
            self.equities_df = pd.read_csv(equities_path, parse_dates=['timestamp'])
            self.equities_df['date'] = pd.to_datetime(self.equities_df['timestamp']).dt.date
            logger.info(f"Loaded equities: {len(self.equities_df)} rows")
            self._build_price_cache()
        else:
            logger.warning(f"Equities file not found: {equities_path}")
            success = False
        
        # Load VIX index (required for VIX strategies)
        vix_path = self.data_dir / 'vix_index.csv'
        if vix_path.exists():
            self.vix_df = pd.read_csv(vix_path, parse_dates=['date'])
            self.vix_df['date'] = pd.to_datetime(self.vix_df['date']).dt.date
            logger.info(f"Loaded VIX index: {len(self.vix_df)} rows")
        else:
            logger.warning(f"VIX file not found: {vix_path}")
        
        # Load rates curve (optional but useful)
        rates_path = self.data_dir / 'rates_curve.csv'
        if rates_path.exists():
            self.rates_df = pd.read_csv(rates_path, parse_dates=['date'])
            self.rates_df['date'] = pd.to_datetime(self.rates_df['date']).dt.date
            logger.info(f"Loaded rates: {len(self.rates_df)} rows")
        
        # Load calendar events (required for event-driven strategies)
        calendar_path = self.data_dir / 'calendar_events.csv'
        if calendar_path.exists():
            self.calendar_df = pd.read_csv(calendar_path, parse_dates=['event_timestamp'])
            self._build_calendar_index()
            logger.info(f"Loaded calendar: {len(self.calendar_df)} events")
        else:
            logger.warning(f"Calendar file not found: {calendar_path}")
        
        # Load options data (optional - needed for realistic pricing)
        options_path = self.data_dir / 'options_eod.csv'
        if options_path.exists():
            try:
                self.options_df = pd.read_csv(options_path, parse_dates=['date', 'expiration'])
                logger.info(f"Loaded options: {len(self.options_df)} rows")
            except Exception as e:
                logger.warning(f"Could not load options data: {e}")
        
        # Load crack spreads (optional - for refiner strategies)
        crack_path = self.data_dir / 'crack_spreads.csv'
        if crack_path.exists():
            try:
                self.crack_df = pd.read_csv(crack_path, parse_dates=['date'])
                self.crack_df['date'] = pd.to_datetime(self.crack_df['date']).dt.date
                logger.info(f"Loaded crack spreads: {len(self.crack_df)} rows")
            except Exception as e:
                logger.warning(f"Could not load crack spreads: {e}")
        
        # Load CFTC COT data (optional - for VIX positioning)
        cftc_path = self.data_dir / 'cftc_cot.csv'
        if cftc_path.exists():
            try:
                self.cftc_df = pd.read_csv(cftc_path, parse_dates=['date'])
                self.cftc_df['date'] = pd.to_datetime(self.cftc_df['date']).dt.date
                logger.info(f"Loaded CFTC COT: {len(self.cftc_df)} rows")
            except Exception as e:
                logger.warning(f"Could not load CFTC data: {e}")
        
        # Load VIX futures (optional - for VIX options pricing)
        vix_futures_path = self.data_dir / 'vix_futures_curve.csv'
        if vix_futures_path.exists():
            try:
                self.vix_futures_df = pd.read_csv(vix_futures_path, parse_dates=['date'])
                self.vix_futures_df['date'] = pd.to_datetime(self.vix_futures_df['date']).dt.date
                logger.info(f"Loaded VIX futures: {len(self.vix_futures_df)} rows")
            except Exception as e:
                logger.warning(f"Could not load VIX futures: {e}")
        
        # Determine date range
        if self.equities_df is not None:
            dates = self.equities_df['date'].unique()
            self.min_date = min(dates)
            self.max_date = max(dates)
            logger.info(f"Data range: {self.min_date} to {self.max_date}")
        
        return success
    
    def _build_price_cache(self):
        """Build fast lookup cache for equity prices."""
        if self.equities_df is None:
            return
        
        for _, row in self.equities_df.iterrows():
            ticker = row['ticker'].upper()
            dt = row['date']
            price = row['close']
            self._price_cache[(ticker, dt)] = price
    
    def _build_calendar_index(self):
        """Build date-indexed calendar lookup."""
        if self.calendar_df is None:
            return
        
        for _, row in self.calendar_df.iterrows():
            event_date = row['event_timestamp'].date() if hasattr(row['event_timestamp'], 'date') else row['event_timestamp']
            event = {
                'event_type': row.get('event_type', 'UNKNOWN'),
                'event_date': event_date,
                'ticker': row.get('ticker', ''),
                'event_label': row.get('event_label', ''),
                'timing': row.get('timing', ''),
                'confirmed': row.get('confirmed', True),
            }
            self._calendar_by_date[event_date].append(event)
    
    def get_price(self, ticker: str, dt: date) -> Optional[float]:
        """Get closing price for a ticker on a specific date."""
        return self._price_cache.get((ticker.upper(), dt))
    
    def get_all_prices(self, dt: date) -> Dict[str, float]:
        """Get all available prices for a date."""
        prices = {}
        if self.equities_df is not None:
            mask = self.equities_df['date'] == dt
            for _, row in self.equities_df[mask].iterrows():
                prices[row['ticker'].upper()] = row['close']
        return prices
    
    def get_vix_spot(self, dt: date) -> Optional[float]:
        """Get VIX spot level for a date."""
        if self.vix_df is None:
            return None

        mask = self.vix_df['date'] == dt
        rows = self.vix_df[mask]
        if len(rows) > 0:
            return float(rows.iloc[0]['vix_close'])

    #Try to find most recent prior date
        prior = self.vix_df[self.vix_df['date'] <= dt].sort_values('date', ascending=False)
        if len(prior) > 0:
            return float(prior.iloc[0]['vix_close'])

        return None
    
    def get_rates(self, dt: date) -> Dict[str, float]:
        """Get interest rates for a date."""
        rates = {}
        if self.rates_df is None:
            return rates
        
        mask = self.rates_df['date'] == dt
        for _, row in self.rates_df[mask].iterrows():
            tenor = row.get('tenor', '')
            rate = row.get('rate_annualized', 0)
            rates[tenor] = rate
        
        return rates
    
    def get_crack_spread(self, dt: date, region: str = 'USGC') -> Optional[float]:
        """Get crack spread for a date and region."""
        if self.crack_df is None:
            return None
        
        mask = self.crack_df['date'] == dt
        rows = self.crack_df[mask]
        
        if len(rows) > 0:
            # Look for region-specific column or default
            if region.lower() in rows.columns:
                return rows.iloc[0][region.lower()]
            elif 'spread' in rows.columns:
                return rows.iloc[0]['spread']
        
        return None
    
    def get_cftc_positioning(self, dt: date) -> Optional[int]:
        """Get CFTC net speculative position as of a date."""
        if self.cftc_df is None:
            return None
        
        # CFTC reports weekly on Tuesday, use most recent report
        prior = self.cftc_df[self.cftc_df['date'] <= dt].sort_values('date', ascending=False)
        if len(prior) > 0:
            row = prior.iloc[0]
            # Net position = longs - shorts for non-commercial traders
            if 'net_position' in row:
                return int(row['net_position'])
            elif 'noncom_long' in row and 'noncom_short' in row:
                return int(row['noncom_long'] - row['noncom_short'])
        
        return None
    
    def get_calendar_events(self, dt: date) -> List[Dict[str, Any]]:
        """Get all calendar events for a date."""
        return self._calendar_by_date.get(dt, [])
    
    def get_upcoming_events(self, dt: date, days_ahead: int = 30) -> List[Dict[str, Any]]:
        """Get events within N days of a date."""
        events = []
        for d in range(days_ahead + 1):
            check_date = dt + timedelta(days=d)
            events.extend(self._calendar_by_date.get(check_date, []))
        return events
    
    def build_snapshot(self, dt: date) -> MarketSnapshot:
        """
        Build a complete MarketSnapshot for a specific date.
        
        This is the primary interface for the backtest engine to get
        all market data for a simulation step.
        """
        timestamp = datetime.combine(dt, datetime.min.time().replace(hour=16))  # 4 PM close
        
        snapshot = MarketSnapshot(
            timestamp=timestamp,
            prices=self.get_all_prices(dt),
            vix_spot=self.get_vix_spot(dt),
            rates=self.get_rates(dt),
            cftc_positioning=self.get_cftc_positioning(dt),
            calendar_events=self.get_upcoming_events(dt, days_ahead=30),
        )
        
        # Add crack spreads
        crack = self.get_crack_spread(dt)
        if crack is not None:
            snapshot.crack_spreads['USGC'] = crack
        
        # Add VIX futures if available
        if self.vix_futures_df is not None:
            mask = self.vix_futures_df['date'] == dt
            for _, row in self.vix_futures_df[mask].iterrows():
                for col in ['vx_m1', 'vx_m2', 'vx_m3', 'vx_m4']:
                    if col in row and pd.notna(row[col]):
                        snapshot.vix_futures[col.upper()] = row[col]
        
        return snapshot
    
    def get_trading_days(self, start: date, end: date) -> List[date]:
        """Get list of trading days in the date range."""
        if self.equities_df is None:
            # Fallback to all weekdays
            days = []
            current = start
            while current <= end:
                if current.weekday() < 5:  # Mon-Fri
                    days.append(current)
                current += timedelta(days=1)
            return days
        
        # Use actual trading days from data
        dates = self.equities_df['date'].unique()
        dates = sorted([d for d in dates if start <= d <= end])
        return dates


# =============================================================================
# OPTIONS PRICER
# =============================================================================

class SimpleOptionsPricer:
    """
    Simple options pricing for backtest when real options data isn't available.
    
    This uses basic Black-Scholes-esque approximations. For more accurate
    backtesting, use real historical options data from ORATS or similar.
    
    Design Note: This is intentionally simple. The goal is to provide
    reasonable estimates for position sizing and P&L tracking, not to
    be a production pricing engine.
    """
    
    def __init__(self, risk_free_rate: float = 0.045):
        self.risk_free_rate = risk_free_rate
    
    def estimate_spread_premium(
        self,
        underlying_price: float,
        long_strike: float,
        short_strike: float,
        dte: int,
        is_call: bool = True,
        iv: float = 0.25
    ) -> Tuple[float, float]:
        """
        Estimate premium for a vertical spread.
        
        Uses simplified Black-Scholes approximation.
        
        Args:
            underlying_price: Current price of underlying
            long_strike: Strike of long leg
            short_strike: Strike of short leg
            dte: Days to expiration
            is_call: True for call spread, False for put spread
            iv: Implied volatility (annualized decimal)
            
        Returns:
            Tuple of (long_leg_premium, short_leg_premium)
        """
        # Time to expiration in years
        t = dte / 365.0
        
        # Very simple approximation based on intrinsic + time value
        # Real pricing would use full BSM
        
        if is_call:
            long_intrinsic = max(0, underlying_price - long_strike)
            short_intrinsic = max(0, underlying_price - short_strike)
        else:
            long_intrinsic = max(0, long_strike - underlying_price)
            short_intrinsic = max(0, short_strike - underlying_price)
        
        # Time value approximation (ATM options have most time value)
        def time_value(strike, price, t, iv):
            moneyness = abs(price - strike) / price
            # Time value decays with moneyness and sqrt of time
            base_tv = price * iv * np.sqrt(t) * 0.4  # 0.4 is rough ATM multiplier
            decay = np.exp(-2 * moneyness)  # Decay with moneyness
            return base_tv * decay
        
        long_time_value = time_value(long_strike, underlying_price, t, iv)
        short_time_value = time_value(short_strike, underlying_price, t, iv)
        
        long_premium = long_intrinsic + long_time_value
        short_premium = short_intrinsic + short_time_value
        
        # Ensure reasonable bounds
        long_premium = max(0.10, long_premium)
        short_premium = max(0.05, short_premium)
        
        # Short leg should be cheaper than long for debit spread
        if is_call:
            if long_strike < short_strike:  # Debit call spread
                short_premium = min(short_premium, long_premium * 0.9)
        else:
            if long_strike > short_strike:  # Debit put spread
                short_premium = min(short_premium, long_premium * 0.9)
        
        return round(long_premium, 2), round(short_premium, 2)
    
    def estimate_single_option_premium(
        self,
        underlying_price: float,
        strike: float,
        dte: int,
        is_call: bool = True,
        iv: float = 0.25
    ) -> float:
        """Estimate premium for a single option."""
        t = dte / 365.0
        
        if is_call:
            intrinsic = max(0, underlying_price - strike)
        else:
            intrinsic = max(0, strike - underlying_price)
        
        moneyness = abs(underlying_price - strike) / underlying_price
        base_tv = underlying_price * iv * np.sqrt(t) * 0.4
        decay = np.exp(-2 * moneyness)
        time_value = base_tv * decay
        
        return round(max(0.10, intrinsic + time_value), 2)
    
    def estimate_current_value(
        self,
        position: Position,
        current_prices: Dict[str, float],
        current_date: date
    ) -> Dict[str, float]:
        """
        Estimate current option prices for marking to market.
        
        Returns dict mapping option_symbol to estimated mid price.
        """
        price_map = {}
        
        for leg in position.legs:
            underlying_price = current_prices.get(leg.underlying, 0)
            if underlying_price == 0:
                # Use entry price if no current price available
                price_map[leg.option_symbol] = leg.entry_price
                continue
            
            dte = (leg.expiration - current_date).days
            if dte <= 0:
                # At or past expiration - use intrinsic value only
                if leg.right == OptionRight.CALL:
                    intrinsic = max(0, underlying_price - leg.strike)
                else:
                    intrinsic = max(0, leg.strike - underlying_price)
                price_map[leg.option_symbol] = intrinsic
            else:
                # Estimate current price
                est_price = self.estimate_single_option_premium(
                    underlying_price,
                    leg.strike,
                    dte,
                    is_call=(leg.right == OptionRight.CALL),
                    iv=0.25  # Default IV
                )
                price_map[leg.option_symbol] = est_price
        
        return price_map


# =============================================================================
# BACKTEST ENGINE
# =============================================================================

class BacktestEngine:
    """
    Main backtest orchestrator.
    
    This class coordinates all components to run a backtest:
    - Loads configuration and data
    - Instantiates strategies
    - Steps through time generating signals
    - Manages positions through Portfolio
    - Tracks and reports performance
    
    Usage:
        engine = BacktestEngine.from_yaml('config/strategies.yaml', variant='base')
        results = engine.run()
        engine.generate_report()
    """
    
    def __init__(
        self,
        config: BacktestConfig,
        strategies: List[BaseStrategy],
        data_manager: DataManager,
        yaml_config: Optional[Dict] = None
    ):
        """
        Initialize the backtest engine.
        
        Args:
            config: BacktestConfig with all settings
            strategies: List of initialized strategy objects
            data_manager: DataManager with loaded data
            yaml_config: Raw parsed YAML for reference
        """
        self.config = config
        self.strategies = {s.name: s for s in strategies}
        self.data_manager = data_manager
        self.yaml_config = yaml_config or {}
        
        # Initialize portfolio
        self.portfolio = Portfolio(
            initial_cash=config.initial_capital,
            commission_per_contract=config.commission_per_contract,
            assignment_fee=config.assignment_fee
        )
        
        # Options pricer for synthetic pricing
        self.pricer = SimpleOptionsPricer()
        
        # Track strategy -> position mapping
        self.strategy_positions: Dict[str, Optional[str]] = {s: None for s in self.strategies}
        
        # Metrics tracking
        self.daily_metrics: List[Dict[str, Any]] = []
        self.signals_log: List[Dict[str, Any]] = []
        self.circuit_breaker_triggered = False
        
        # Theme mapping for exposure tracking
        self.theme_map = {
            name: strat.config.theme for name, strat in self.strategies.items()
        }
        
        logger.info(f"BacktestEngine initialized with {len(strategies)} strategies")
        logger.info(f"Capital: ${config.initial_capital:,.2f}, Variant: {config.variant}")
    
    @classmethod
    def from_yaml(
        cls,
        yaml_path: str = 'config/strategies.yaml',
        variant: str = 'base',
        start_date: str = '2026-01-21',
        end_date: str = '2026-02-28',
        data_dir: Optional[str] = None
    ) -> 'BacktestEngine':
        """
        Factory method to create BacktestEngine from YAML configuration.
        
        Args:
            yaml_path: Path to strategies.yaml
            variant: Portfolio variant (conservative, base, aggressive)
            start_date: Backtest start date (YYYY-MM-DD)
            end_date: Backtest end date (YYYY-MM-DD)
            data_dir: Optional override for data directory
            
        Returns:
            Configured BacktestEngine ready to run
        """
        yaml_path = Path(yaml_path)
        if not yaml_path.is_absolute():
            yaml_path = PROJECT_ROOT / yaml_path
        
        # Load YAML
        with open(yaml_path, 'r') as f:
            yaml_config = yaml.safe_load(f)
        
        # Create config
        config = BacktestConfig.from_yaml(yaml_config, variant, start_date, end_date)
        
        # Load data
        data_path = Path(data_dir) if data_dir else DATA_RAW
        data_manager = DataManager(data_path)
        data_manager.load_all()
        
        # Create strategies
        strategies = []
        strategies_config = yaml_config.get('strategies', {})
        
        for name, strat_config in strategies_config.items():
            if not strat_config.get('enabled', True):
                logger.debug(f"Skipping disabled strategy: {name}")
                continue
            
            # Check if strategy has allocation in this variant
            sizing = strat_config.get('position_sizing', {})
            allocation = sizing.get(variant, 0)
            
            if allocation <= 0:
                logger.debug(f"Skipping {name} - no allocation in {variant} variant")
                continue
            
            try:
                parsed_config = StrategyConfig.from_yaml(name, strat_config)
                strategy = create_strategy(parsed_config)
                strategies.append(strategy)
                logger.info(f"Loaded strategy: {name} (${allocation} allocation)")
            except Exception as e:
                logger.warning(f"Could not load strategy {name}: {e}")
        
        return cls(config, strategies, data_manager, yaml_config)
    
    def run(self) -> Dict[str, Any]:
        """
        Execute the backtest.
        
        Returns:
            Dict with backtest results including final NAV, returns, metrics
        """
        logger.info("=" * 60)
        logger.info("STARTING BACKTEST")
        logger.info(f"  Period: {self.config.start_date} to {self.config.end_date}")
        logger.info(f"  Variant: {self.config.variant}")
        logger.info(f"  Capital: ${self.config.initial_capital:,.2f}")
        logger.info("=" * 60)
        
        # Get trading days
        trading_days = self.data_manager.get_trading_days(
            self.config.start_date, 
            self.config.end_date
        )
        
        if not trading_days:
            logger.error("No trading days in date range!")
            return {'error': 'No trading days'}
        
        logger.info(f"Simulating {len(trading_days)} trading days")
        
        # Reset all strategies
        for strategy in self.strategies.values():
            strategy.reset()
        
        # Main simulation loop
        for i, current_date in enumerate(trading_days):
            if self.circuit_breaker_triggered:
                logger.warning(f"Circuit breaker triggered - stopping simulation")
                break
            
            # Build market snapshot
            snapshot = self.data_manager.build_snapshot(current_date)
            
            # Process the trading day
            self._process_day(current_date, snapshot)
            
            # Record daily metrics
            self._record_daily_metrics(current_date, snapshot)
            
            # Check circuit breaker
            self._check_circuit_breaker(current_date)
            
            # Progress logging
            if (i + 1) % 5 == 0 or i == len(trading_days) - 1:
                nav = self.portfolio.nav
                logger.info(f"Day {i+1}/{len(trading_days)}: {current_date} | NAV: ${nav:,.2f}")
        
        # Close remaining positions at end
        self._close_all_positions(trading_days[-1], "BACKTEST_END")
        
        # Generate results
        results = self._generate_results()
        
        logger.info("=" * 60)
        logger.info("BACKTEST COMPLETE")
        logger.info(f"  Final NAV: ${results['final_nav']:,.2f}")
        logger.info(f"  Total Return: {results['total_return_pct']:.2f}%")
        logger.info(f"  Max Drawdown: {results['max_drawdown_pct']:.2f}%")
        logger.info("=" * 60)
        
        return results
    
    def _process_day(self, current_date: date, snapshot: MarketSnapshot):
        """Process a single trading day."""
        
        # 1. Mark existing positions to market
        self._mark_positions(current_date, snapshot)
        
        # 2. Check exit conditions for open positions
        self._check_exits(snapshot)
        
        # 3. Check entry conditions for strategies without positions
        self._check_entries(snapshot)
    
    def _mark_positions(self, current_date: date, snapshot: MarketSnapshot):
        """Mark all open positions to market."""
        if not self.portfolio.positions:
            return
        
        # Build price map for all open positions
        price_map = {}
        for position in self.portfolio.positions.values():
            est_prices = self.pricer.estimate_current_value(
                position,
                snapshot.prices,
                current_date
            )
            price_map.update(est_prices)
        
        # Mark to market
        self.portfolio.mark_to_market(snapshot.timestamp, price_map)
    
    def _check_exits(self, snapshot: MarketSnapshot):
        """Check exit conditions for all open positions."""
        
        # Collect positions to close (can't modify dict during iteration)
        exits_to_process = []
        
        for strategy_name, position_id in self.strategy_positions.items():
            if position_id is None:
                continue
            
            if position_id not in self.portfolio.positions:
                # Position already closed
                self.strategy_positions[strategy_name] = None
                continue
            
            position = self.portfolio.positions[position_id]
            strategy = self.strategies.get(strategy_name)
            
            if strategy is None:
                continue
            
            # Calculate P&L percentage for exit evaluation
            pnl_pct = position.pnl_pct
            
            # Check strategy exit conditions
            signal = strategy.check_exit(snapshot, position, pnl_pct)
            
            if signal and signal.signal_type in (SignalType.EXIT_FULL, SignalType.EXIT_PARTIAL):
                exits_to_process.append((strategy_name, position_id, signal))
        
        # Process exits
        for strategy_name, position_id, signal in exits_to_process:
            self._process_exit(position_id, signal, snapshot)
            
            if signal.signal_type == SignalType.EXIT_FULL:
                self.strategy_positions[strategy_name] = None
            
            self.signals_log.append(signal.to_dict())
    
    def _check_entries(self, snapshot: MarketSnapshot):
        """Check entry conditions for strategies without open positions."""
        
        for strategy_name, strategy in self.strategies.items():
            # Skip if already have a position
            if self.strategy_positions.get(strategy_name) is not None:
                continue
            
            # Check entry conditions
            signal = strategy.check_entry(snapshot)
            
            if signal and signal.signal_type == SignalType.ENTRY:
                position_id = self._process_entry(signal, snapshot)
                
                if position_id:
                    self.strategy_positions[strategy_name] = position_id
                    self.signals_log.append(signal.to_dict())
    
    def _process_entry(self, signal: Signal, snapshot: MarketSnapshot) -> Optional[str]:
        """
        Process an entry signal and open a position.
        
        Returns:
            position_id if successful, None otherwise
        """
        structure = signal.target_structure
        if not structure:
            logger.warning(f"Entry signal missing target_structure: {signal}")
            return None
        
        strategy = self.strategies.get(signal.strategy_name)
        if not strategy:
            return None
        
        # Get sizing from config
        allocation = strategy.config.get_sizing(self.config.variant)
        if allocation <= 0:
            logger.debug(f"No allocation for {signal.strategy_name} in {self.config.variant}")
            return None
        
        # Get underlying price
        underlying_price = snapshot.get_price(structure['underlying'])
        if not underlying_price:
            logger.warning(f"No price for {structure['underlying']}")
            return None
        
        # Calculate option prices
        dte = (structure['expiration'] - snapshot.timestamp.date()).days
        is_call = structure['right'] == 'C'
        
        if 'spread' in structure['structure_type']:
            # Vertical spread
            long_price, short_price = self.pricer.estimate_spread_premium(
                underlying_price,
                structure['long_strike'],
                structure['short_strike'],
                dte,
                is_call
            )
            
            # Calculate how many spreads we can afford
            net_premium = (long_price - short_price) * 100  # Per spread
            max_spreads = int(allocation / net_premium) if net_premium > 0 else 1
            quantity = max(1, min(max_spreads, 5))  # Cap at 5 spreads
            
            # Check risk limits
            max_loss = net_premium * quantity
            can_open, reason = self.portfolio.can_open_position(
                max_loss,
                self.config.max_position_loss_pct,
                self.config.max_aggregate_premium_pct
            )
            
            if not can_open:
                logger.warning(f"Cannot open {signal.strategy_name}: {reason}")
                return None
            
            # Create position
            position = Position.create_spread(
                strategy_name=signal.strategy_name,
                underlying=structure['underlying'],
                long_strike=structure['long_strike'],
                short_strike=structure['short_strike'],
                expiration=structure['expiration'],
                right=OptionRight.CALL if is_call else OptionRight.PUT,
                long_price=long_price,
                short_price=short_price,
                quantity=quantity,
                entry_timestamp=snapshot.timestamp,
                entry_nav=self.portfolio.nav
            )
            
        else:
            # Single option (protective put, etc.)
            option_price = self.pricer.estimate_single_option_premium(
                underlying_price,
                structure['strike'],
                dte,
                is_call
            )
            
            quantity = max(1, int(allocation / (option_price * 100)))
            
            # Check risk limits
            max_loss = option_price * 100 * quantity
            can_open, reason = self.portfolio.can_open_position(
                max_loss,
                self.config.max_position_loss_pct,
                self.config.max_aggregate_premium_pct
            )
            
            if not can_open:
                logger.warning(f"Cannot open {signal.strategy_name}: {reason}")
                return None
            
            position = Position.create_single_option(
                strategy_name=signal.strategy_name,
                underlying=structure['underlying'],
                strike=structure['strike'],
                expiration=structure['expiration'],
                right=OptionRight.CALL if is_call else OptionRight.PUT,
                price=option_price,
                quantity=quantity,
                entry_timestamp=snapshot.timestamp,
                entry_nav=self.portfolio.nav
            )
        
        # Open the position
        try:
            position_id = self.portfolio.open_position(position)
            logger.info(
                f"ENTRY: {signal.strategy_name} | "
                f"Premium: ${position.net_premium:.2f} | "
                f"Max Loss: ${position.max_loss:.2f}"
            )
            return position_id
        except ValueError as e:
            logger.warning(f"Could not open position: {e}")
            return None
    
    def _process_exit(self, position_id: str, signal: Signal, snapshot: MarketSnapshot):
        """Process an exit signal and close a position."""
        
        try:
            # Build price map for closing
            position = self.portfolio.positions[position_id]
            price_map = self.pricer.estimate_current_value(
                position,
                snapshot.prices,
                snapshot.timestamp.date()
            )
            
            realized_pnl = self.portfolio.close_position(
                position_id,
                snapshot.timestamp,
                signal.exit_reason.value if signal.exit_reason else "UNKNOWN",
                price_map
            )
            
            logger.info(
                f"EXIT: {signal.strategy_name} | "
                f"Reason: {signal.exit_reason.value if signal.exit_reason else 'N/A'} | "
                f"Realized P&L: ${realized_pnl:.2f}"
            )
            
        except KeyError as e:
            logger.warning(f"Could not close position {position_id}: {e}")
    
    def _close_all_positions(self, final_date: date, reason: str):
        """Close all remaining open positions."""
        snapshot = self.data_manager.build_snapshot(final_date)
        
        for position_id in list(self.portfolio.positions.keys()):
            position = self.portfolio.positions[position_id]
            
            price_map = self.pricer.estimate_current_value(
                position,
                snapshot.prices,
                final_date
            )
            
            try:
                self.portfolio.close_position(
                    position_id,
                    snapshot.timestamp,
                    reason,
                    price_map
                )
            except Exception as e:
                logger.warning(f"Error closing position {position_id}: {e}")
        
        # Clear position tracking
        for strategy_name in self.strategy_positions:
            self.strategy_positions[strategy_name] = None
    
    def _record_daily_metrics(self, current_date: date, snapshot: MarketSnapshot):
        """Record daily performance metrics."""
        summary = self.portfolio.summary()
        
        metrics = {
            'date': current_date.isoformat(),
            'nav': summary['nav'],
            'cash': summary['cash'],
            'open_positions': summary['open_positions'],
            'total_premium_at_risk': summary['total_premium_at_risk'],
            'premium_at_risk_pct': summary['premium_at_risk_pct'],
            'total_return_pct': summary['total_return_pct'],
            'current_drawdown_pct': summary['current_drawdown_pct'],
            'vix_spot': snapshot.vix_spot,
        }
        
        self.daily_metrics.append(metrics)
    
    def _check_circuit_breaker(self, current_date: date):
        """Check if circuit breaker should be triggered."""
        if len(self.daily_metrics) < 5:
            return
        
        # Check weekly drawdown
        recent = self.daily_metrics[-5:]
        week_start_nav = recent[0]['nav']
        current_nav = recent[-1]['nav']
        
        weekly_return = (current_nav - week_start_nav) / week_start_nav
        
        if weekly_return < -self.config.circuit_breaker_weekly_drawdown:
            logger.warning(
                f"CIRCUIT BREAKER: Weekly drawdown {weekly_return*100:.2f}% "
                f"exceeds limit {self.config.circuit_breaker_weekly_drawdown*100:.1f}%"
            )
            self.circuit_breaker_triggered = True
    
    def _generate_results(self) -> Dict[str, Any]:
        """Generate comprehensive backtest results."""
        summary = self.portfolio.summary()
        
        # Calculate additional metrics
        if self.daily_metrics:
            nav_series = pd.Series([m['nav'] for m in self.daily_metrics])
            returns_series = nav_series.pct_change().dropna()
            
            sharpe = 0
            if len(returns_series) > 1 and returns_series.std() > 0:
                sharpe = (returns_series.mean() / returns_series.std()) * np.sqrt(252)
            
            # Win rate
            closed = self.portfolio.closed_positions
            if closed:
                wins = sum(1 for p in closed if p.unrealized_pnl > 0)
                win_rate = wins / len(closed) * 100
            else:
                win_rate = 0
        else:
            sharpe = 0
            win_rate = 0
        
        return {
            'final_nav': summary['nav'],
            'initial_nav': self.config.initial_capital,
            'total_return_pct': summary['total_return_pct'],
            'max_drawdown_pct': summary['max_drawdown_pct'],
            'sharpe_ratio': sharpe,
            'win_rate_pct': win_rate,
            'total_trades': len(self.portfolio.closed_positions),
            'open_positions': summary['open_positions'],
            'cash_remaining': summary['cash'],
            'circuit_breaker_triggered': self.circuit_breaker_triggered,
            'variant': self.config.variant,
            'start_date': self.config.start_date.isoformat(),
            'end_date': self.config.end_date.isoformat(),
            'daily_metrics': self.daily_metrics,
            'trade_log': self.portfolio.trade_log,
            'signals_log': self.signals_log,
        }
    
    def generate_report(self, output_path: Optional[str] = None) -> str:
        """
        Generate a text report of backtest results.
        
        Args:
            output_path: Optional path to save report
            
        Returns:
            Report text
        """
        results = self._generate_results()
        
        lines = [
            "=" * 70,
            "RAIDILLON BACKTEST REPORT",
            "=" * 70,
            "",
            f"Period: {results['start_date']} to {results['end_date']}",
            f"Variant: {results['variant'].upper()}",
            f"Initial Capital: ${results['initial_nav']:,.2f}",
            "",
            "-" * 70,
            "PERFORMANCE SUMMARY",
            "-" * 70,
            f"Final NAV:        ${results['final_nav']:,.2f}",
            f"Total Return:     {results['total_return_pct']:+.2f}%",
            f"Max Drawdown:     {results['max_drawdown_pct']:.2f}%",
            f"Sharpe Ratio:     {results['sharpe_ratio']:.2f}",
            f"Win Rate:         {results['win_rate_pct']:.1f}%",
            f"Total Trades:     {results['total_trades']}",
            "",
            "-" * 70,
            "TRADE LOG",
            "-" * 70,
        ]
        
        for trade in results['trade_log']:
            action = trade.get('action', '')
            strategy = trade.get('strategy', '')
            underlying = trade.get('underlying', '')
            
            if action == 'OPEN':
                premium = trade.get('premium', 0)
                lines.append(f"  {trade['timestamp'][:10]} | OPEN  | {strategy:<30} | Premium: ${premium:,.2f}")
            else:
                pnl = trade.get('realized_pnl', 0)
                reason = trade.get('reason', '')
                lines.append(f"  {trade['timestamp'][:10]} | CLOSE | {strategy:<30} | P&L: ${pnl:+,.2f} ({reason})")
        
        lines.extend([
            "",
            "-" * 70,
            "SIGNALS LOG",
            "-" * 70,
        ])
        
        for signal in results['signals_log'][:20]:  # Limit to 20 signals
            sig_type = signal.get('signal_type', '')
            strategy = signal.get('strategy_name', '')
            lines.append(f"  {signal['timestamp'][:10]} | {sig_type:<12} | {strategy}")
        
        if len(results['signals_log']) > 20:
            lines.append(f"  ... and {len(results['signals_log']) - 20} more signals")
        
        lines.extend([
            "",
            "=" * 70,
            "END OF REPORT",
            "=" * 70,
        ])
        
        report = "\n".join(lines)
        
        if output_path:
            with open(output_path, 'w') as f:
                f.write(report)
            logger.info(f"Report saved to {output_path}")
        
        return report
    
    def export_results(self, output_dir: Optional[str] = None):
        """Export all results to CSV files."""
        output_dir = Path(output_dir) if output_dir else self.config.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Export daily metrics
        if self.daily_metrics:
            df = pd.DataFrame(self.daily_metrics)
            path = output_dir / f'daily_metrics_{timestamp}.csv'
            df.to_csv(path, index=False)
            logger.info(f"Daily metrics exported to {path}")
        
        # Export trade log
        if self.portfolio.trade_log:
            df = pd.DataFrame(self.portfolio.trade_log)
            path = output_dir / f'trade_log_{timestamp}.csv'
            df.to_csv(path, index=False)
            logger.info(f"Trade log exported to {path}")
        
        # Export signals
        if self.signals_log:
            df = pd.DataFrame(self.signals_log)
            path = output_dir / f'signals_{timestamp}.csv'
            df.to_csv(path, index=False)
            logger.info(f"Signals exported to {path}")
        
        # Export report
        report_path = output_dir / f'report_{timestamp}.txt'
        self.generate_report(str(report_path))


# =============================================================================
# CLI INTERFACE
# =============================================================================

def main():
    """Command-line entry point for running backtests."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Run Raidillon Backtest')
    parser.add_argument('--config', default='config/strategies.yaml', help='Path to strategies.yaml')
    parser.add_argument('--variant', default='base', choices=['conservative', 'base', 'aggressive'])
    parser.add_argument('--start', default='2026-01-21', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', default='2026-02-28', help='End date (YYYY-MM-DD)')
    parser.add_argument('--data-dir', help='Override data directory')
    parser.add_argument('--output-dir', help='Output directory for results')
    parser.add_argument('--quiet', action='store_true', help='Reduce logging output')
    
    args = parser.parse_args()
    
    if args.quiet:
        logging.getLogger('raidillon').setLevel(logging.WARNING)
    
    # Create and run engine
    engine = BacktestEngine.from_yaml(
        yaml_path=args.config,
        variant=args.variant,
        start_date=args.start,
        end_date=args.end,
        data_dir=args.data_dir
    )
    
    results = engine.run()
    
    # Generate outputs
    print("\n" + engine.generate_report())
    engine.export_results(args.output_dir)
    
    return results


if __name__ == "__main__":
    main()
