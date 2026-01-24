"""
portfolio.py - Portfolio and Position Management for Raidillon Backtest Engine

This module implements the core data structures for tracking positions, cash,
and NAV throughout a backtest. It handles multi-leg option spreads as atomic
units and provides methods for mark-to-market valuation.

Key Design Decisions:
1. Positions are immutable once created - modifications create new Position objects
2. Multi-leg spreads are tracked as a single Position with multiple Leg objects
3. Cash is tracked separately from positions for clarity
4. NAV is calculated on-demand to ensure consistency
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Optional, Dict, Any
from enum import Enum
import uuid


class PositionSide(Enum):
    """Whether the position is long or short overall."""
    LONG = "LONG"
    SHORT = "SHORT"


class OptionRight(Enum):
    """Call or Put."""
    CALL = "C"
    PUT = "P"


class PositionStatus(Enum):
    """Lifecycle status of a position."""
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"
    EXERCISED = "EXERCISED"
    ASSIGNED = "ASSIGNED"


@dataclass
class Leg:
    """
    Represents a single leg of an option position.
    
    For a debit call spread:
    - Long leg: quantity > 0, right = CALL
    - Short leg: quantity < 0, right = CALL
    
    Attributes:
        underlying: The ticker symbol (e.g., 'VLO', 'VIX')
        expiration: Option expiration date
        strike: Strike price
        right: CALL or PUT
        quantity: Number of contracts (positive = long, negative = short)
        entry_price: Price paid/received per contract at entry
        current_price: Most recent mark-to-market price
    """
    underlying: str
    expiration: date
    strike: float
    right: OptionRight
    quantity: int  # Positive = long, Negative = short
    entry_price: float
    current_price: float = 0.0
    
    @property
    def is_long(self) -> bool:
        return self.quantity > 0
    
    @property
    def option_symbol(self) -> str:
        """Generate OCC-style option symbol."""
        # Format: UNDERLYING + YYMMDD + C/P + STRIKE(8 digits, padded)
        exp_str = self.expiration.strftime("%y%m%d")
        right_str = "C" if self.right == OptionRight.CALL else "P"
        strike_str = f"{int(self.strike * 1000):08d}"
        return f"{self.underlying}{exp_str}{right_str}{strike_str}"
    
    @property
    def entry_value(self) -> float:
        """Total value at entry (premium paid or received)."""
        # Options are quoted per share, contracts are 100 shares
        # Long position: negative cash flow (pay premium)
        # Short position: positive cash flow (receive premium)
        return -self.quantity * self.entry_price * 100
    
    @property
    def current_value(self) -> float:
        """Current mark-to-market value."""
        return self.quantity * self.current_price * 100
    
    @property
    def pnl(self) -> float:
        """Unrealized P&L for this leg."""
        return self.current_value - (-self.entry_value)


@dataclass
class Position:
    """
    Represents a complete position, which may consist of multiple legs.
    
    For a simple long call: one leg with positive quantity
    For a debit call spread: two legs (long lower strike, short higher strike)
    For a protective put: one leg with positive quantity (put)
    
    The Position tracks all legs together and calculates aggregate metrics.
    
    Attributes:
        position_id: Unique identifier for this position
        strategy_name: Name of the strategy that generated this position
        underlying: Primary underlying symbol
        legs: List of option legs comprising this position
        entry_timestamp: When the position was opened
        entry_nav: Portfolio NAV at time of entry (for sizing validation)
        status: Current lifecycle status
        notes: Optional notes or tags for analysis
    """
    position_id: str
    strategy_name: str
    underlying: str
    legs: List[Leg]
    entry_timestamp: datetime
    entry_nav: float
    status: PositionStatus = PositionStatus.OPEN
    close_timestamp: Optional[datetime] = None
    close_reason: Optional[str] = None
    notes: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def create_spread(
        cls,
        strategy_name: str,
        underlying: str,
        long_strike: float,
        short_strike: float,
        expiration: date,
        right: OptionRight,
        long_price: float,
        short_price: float,
        quantity: int,
        entry_timestamp: datetime,
        entry_nav: float
    ) -> "Position":
        """
        Factory method to create a standard vertical spread.
        
        For a DEBIT spread (pay premium to enter):
        - Debit call spread: buy lower strike call, sell higher strike call
        - Debit put spread: buy higher strike put, sell lower strike put
        
        Args:
            strategy_name: Name of the generating strategy
            underlying: Ticker symbol
            long_strike: Strike price for the long leg
            short_strike: Strike price for the short leg
            expiration: Option expiration date
            right: CALL or PUT
            long_price: Premium paid for long leg (per contract)
            short_price: Premium received for short leg (per contract)
            quantity: Number of spreads (always positive)
            entry_timestamp: When opened
            entry_nav: Portfolio NAV at entry
        
        Returns:
            New Position object representing the spread
        """
        legs = [
            Leg(
                underlying=underlying,
                expiration=expiration,
                strike=long_strike,
                right=right,
                quantity=quantity,  # Long
                entry_price=long_price,
            ),
            Leg(
                underlying=underlying,
                expiration=expiration,
                strike=short_strike,
                right=right,
                quantity=-quantity,  # Short
                entry_price=short_price,
            ),
        ]
        
        return cls(
            position_id=str(uuid.uuid4())[:8],
            strategy_name=strategy_name,
            underlying=underlying,
            legs=legs,
            entry_timestamp=entry_timestamp,
            entry_nav=entry_nav,
        )
    
    @classmethod
    def create_single_option(
        cls,
        strategy_name: str,
        underlying: str,
        strike: float,
        expiration: date,
        right: OptionRight,
        price: float,
        quantity: int,
        entry_timestamp: datetime,
        entry_nav: float
    ) -> "Position":
        """Factory method for a single-leg option position (e.g., protective put)."""
        legs = [
            Leg(
                underlying=underlying,
                expiration=expiration,
                strike=strike,
                right=right,
                quantity=quantity,
                entry_price=price,
            )
        ]
        
        return cls(
            position_id=str(uuid.uuid4())[:8],
            strategy_name=strategy_name,
            underlying=underlying,
            legs=legs,
            entry_timestamp=entry_timestamp,
            entry_nav=entry_nav,
        )
    
    @property
    def is_spread(self) -> bool:
        """True if this position has multiple legs."""
        return len(self.legs) > 1
    
    @property
    def net_premium(self) -> float:
        """
        Net premium paid (positive) or received (negative) at entry.
        For a debit spread, this is the debit amount (positive).
        """
        return sum(leg.entry_value for leg in self.legs)
    
    @property
    def max_loss(self) -> float:
        """
        Maximum possible loss for this position.
        For a debit spread: the net premium paid.
        For a credit spread: spread width minus premium received.
        For a long option: the premium paid.
        """
        if not self.is_spread:
            # Single option: max loss is premium if long
            leg = self.legs[0]
            if leg.is_long:
                return abs(leg.entry_value)
            else:
                # Short option: theoretically unlimited, but we don't do naked shorts
                raise ValueError("Naked short options not supported")
        
        # For spreads, calculate based on spread width
        strikes = [leg.strike for leg in self.legs]
        spread_width = abs(max(strikes) - min(strikes))
        
        # Determine if debit or credit spread
        if self.net_premium > 0:
            # Debit spread: max loss is premium paid
            return self.net_premium
        else:
            # Credit spread: max loss is spread width minus premium received
            quantity = abs(self.legs[0].quantity)
            return (spread_width * 100 * quantity) + self.net_premium
    
    @property
    def max_profit(self) -> float:
        """
        Maximum possible profit for this position.
        For a debit spread: spread width minus premium paid.
        For a credit spread: the premium received.
        """
        if not self.is_spread:
            leg = self.legs[0]
            if leg.is_long:
                # Long option: theoretically unlimited for calls
                return float('inf') if leg.right == OptionRight.CALL else leg.strike * 100 * leg.quantity
            else:
                # Short option: premium received (not supported)
                raise ValueError("Naked short options not supported")
        
        strikes = [leg.strike for leg in self.legs]
        spread_width = abs(max(strikes) - min(strikes))
        quantity = abs(self.legs[0].quantity)
        
        if self.net_premium > 0:
            # Debit spread: max profit is spread width minus premium
            return (spread_width * 100 * quantity) - self.net_premium
        else:
            # Credit spread: max profit is premium received
            return abs(self.net_premium)
    
    @property
    def current_value(self) -> float:
        """Current mark-to-market value of the position."""
        return sum(leg.current_value for leg in self.legs)
    
    @property
    def unrealized_pnl(self) -> float:
        """Unrealized P&L (current value minus entry cost)."""
        return self.current_value - (-self.net_premium)
    
    @property
    def pnl_pct(self) -> float:
        """P&L as percentage of premium risked."""
        if self.max_loss == 0:
            return 0.0
        return (self.unrealized_pnl / self.max_loss) * 100
    
    def update_prices(self, price_map: Dict[str, float]) -> None:
        """
        Update current prices for all legs.
        
        Args:
            price_map: Dict mapping option_symbol to current mid price
        """
        for leg in self.legs:
            if leg.option_symbol in price_map:
                leg.current_price = price_map[leg.option_symbol]
    
    def close(self, timestamp: datetime, reason: str) -> None:
        """Mark the position as closed."""
        self.status = PositionStatus.CLOSED
        self.close_timestamp = timestamp
        self.close_reason = reason
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert position to dictionary for logging/export."""
        return {
            "position_id": self.position_id,
            "strategy_name": self.strategy_name,
            "underlying": self.underlying,
            "num_legs": len(self.legs),
            "net_premium": self.net_premium,
            "max_loss": self.max_loss,
            "max_profit": self.max_profit if self.max_profit != float('inf') else "unlimited",
            "current_value": self.current_value,
            "unrealized_pnl": self.unrealized_pnl,
            "pnl_pct": self.pnl_pct,
            "status": self.status.value,
            "entry_timestamp": self.entry_timestamp.isoformat(),
            "close_timestamp": self.close_timestamp.isoformat() if self.close_timestamp else None,
            "close_reason": self.close_reason,
        }


class Portfolio:
    """
    Manages a collection of positions and cash for the backtest.
    
    The Portfolio is the central accounting entity. It tracks:
    - All open and closed positions
    - Cash balance
    - NAV over time
    - Trade history
    
    Thread Safety: This class is NOT thread-safe. Use only in single-threaded
    backtest loop.
    
    Attributes:
        initial_cash: Starting cash balance
        cash: Current cash balance
        positions: Dict of position_id -> Position for open positions
        closed_positions: List of closed positions for history
        nav_history: List of (timestamp, nav) tuples
        trade_log: List of trade records for attribution
    """
    
    def __init__(
        self,
        initial_cash: float = 10000.0,
        commission_per_contract: float = 0.65,
        assignment_fee: float = 5.00
    ):
        """
        Initialize a new Portfolio.
        
        Args:
            initial_cash: Starting cash balance (default $10,000)
            commission_per_contract: Per-contract commission (default $0.65)
            assignment_fee: Fee for exercise/assignment (default $5.00)
        """
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.commission_per_contract = commission_per_contract
        self.assignment_fee = assignment_fee
        
        self.positions: Dict[str, Position] = {}
        self.closed_positions: List[Position] = []
        self.nav_history: List[tuple] = []
        self.trade_log: List[Dict[str, Any]] = []
        
    @property
    def nav(self) -> float:
        """
        Current Net Asset Value = Cash + Sum of position values.
        
        This is calculated on-demand to ensure accuracy.
        """
        position_value = sum(p.current_value for p in self.positions.values())
        return self.cash + position_value
    
    @property
    def total_premium_at_risk(self) -> float:
        """Sum of max_loss across all open positions."""
        return sum(p.max_loss for p in self.positions.values())
    
    @property
    def gross_exposure(self) -> float:
        """
        Gross exposure as sum of absolute position values.
        Used for exposure limits checking.
        """
        return sum(abs(p.current_value) for p in self.positions.values())
    
    def can_open_position(
        self,
        max_loss: float,
        max_position_loss_pct: float = 0.04,
        max_aggregate_premium_pct: float = 0.20
    ) -> tuple:
        """
        Check if a new position meets risk limits.
        
        Args:
            max_loss: The max loss of the proposed position
            max_position_loss_pct: Max single position as pct of NAV
            max_aggregate_premium_pct: Max total premium as pct of NAV
        
        Returns:
            (can_open: bool, rejection_reason: Optional[str])
        """
        current_nav = self.nav
        
        # Check single position limit
        if max_loss > current_nav * max_position_loss_pct:
            return False, f"Position max_loss ${max_loss:.2f} exceeds {max_position_loss_pct*100}% of NAV (${current_nav * max_position_loss_pct:.2f})"
        
        # Check aggregate premium limit
        new_total_premium = self.total_premium_at_risk + max_loss
        if new_total_premium > current_nav * max_aggregate_premium_pct:
            return False, f"Total premium at risk ${new_total_premium:.2f} would exceed {max_aggregate_premium_pct*100}% of NAV"
        
        # Check cash available
        if max_loss > self.cash:
            return False, f"Insufficient cash: ${self.cash:.2f} available, ${max_loss:.2f} required"
        
        return True, None
    
    def open_position(self, position: Position) -> str:
        """
        Add a new position to the portfolio.
        
        This method:
        1. Validates the position can be opened
        2. Deducts premium from cash
        3. Applies commissions
        4. Records the trade
        
        Args:
            position: The Position object to add
        
        Returns:
            position_id of the opened position
        
        Raises:
            ValueError: If position cannot be opened (risk limits, etc.)
        """
        # Calculate total contracts for commission
        total_contracts = sum(abs(leg.quantity) for leg in position.legs)
        commission = total_contracts * self.commission_per_contract
        
        # Check we have enough cash
        required_cash = position.net_premium + commission
        if required_cash > self.cash:
            raise ValueError(
                f"Insufficient cash: ${self.cash:.2f} available, "
                f"${required_cash:.2f} required (premium + commission)"
            )
        
        # Deduct from cash
        self.cash -= required_cash
        
        # Add to positions
        self.positions[position.position_id] = position
        
        # Log the trade
        self.trade_log.append({
            "timestamp": position.entry_timestamp.isoformat(),
            "action": "OPEN",
            "position_id": position.position_id,
            "strategy": position.strategy_name,
            "underlying": position.underlying,
            "premium": position.net_premium,
            "commission": commission,
            "cash_after": self.cash,
            "nav_after": self.nav,
        })
        
        return position.position_id
    
    def close_position(
        self,
        position_id: str,
        timestamp: datetime,
        reason: str,
        fill_prices: Optional[Dict[str, float]] = None
    ) -> float:
        """
        Close an open position.
        
        Args:
            position_id: ID of the position to close
            timestamp: Close timestamp
            reason: Reason for closing (take_profit, stop_loss, time_stop, etc.)
            fill_prices: Optional dict of option_symbol -> fill price
                        If None, uses current_price from last mark
        
        Returns:
            Realized P&L from closing the position
        
        Raises:
            KeyError: If position_id not found
        """
        if position_id not in self.positions:
            raise KeyError(f"Position {position_id} not found in open positions")
        
        position = self.positions[position_id]
        
        # Update prices if provided
        if fill_prices:
            position.update_prices(fill_prices)
        
        # Calculate proceeds from closing
        # Closing a long position: sell at bid -> receive cash
        # Closing a short position: buy at ask -> pay cash
        close_value = position.current_value
        
        # Calculate commission
        total_contracts = sum(abs(leg.quantity) for leg in position.legs)
        commission = total_contracts * self.commission_per_contract
        
        # Update cash
        self.cash += close_value - commission
        
        # Calculate realized P&L
        realized_pnl = close_value - (-position.net_premium) - 2 * commission  # Entry + exit commission
        
        # Mark position as closed
        position.close(timestamp, reason)
        
        # Move to closed positions
        self.closed_positions.append(position)
        del self.positions[position_id]
        
        # Log the trade
        self.trade_log.append({
            "timestamp": timestamp.isoformat(),
            "action": "CLOSE",
            "position_id": position_id,
            "strategy": position.strategy_name,
            "underlying": position.underlying,
            "close_value": close_value,
            "realized_pnl": realized_pnl,
            "reason": reason,
            "commission": commission,
            "cash_after": self.cash,
            "nav_after": self.nav,
        })
        
        return realized_pnl
    
    def mark_to_market(self, timestamp: datetime, price_map: Dict[str, float]) -> float:
        """
        Update all position values and record NAV.
        
        This should be called at each bar/tick to maintain accurate valuations.
        
        Args:
            timestamp: Current timestamp
            price_map: Dict mapping option_symbol to current mid price
        
        Returns:
            Current NAV after marking
        """
        # Update all position prices
        for position in self.positions.values():
            position.update_prices(price_map)
        
        # Record NAV
        current_nav = self.nav
        self.nav_history.append((timestamp, current_nav))
        
        return current_nav
    
    def calculate_drawdown(self) -> tuple:
        """
        Calculate current and maximum drawdown.
        
        Returns:
            (current_drawdown_pct, max_drawdown_pct, high_water_mark)
        """
        if not self.nav_history:
            return 0.0, 0.0, self.initial_cash
        
        navs = [nav for _, nav in self.nav_history]
        
        # Calculate running max (high water mark)
        high_water = navs[0]
        max_drawdown = 0.0
        
        for nav in navs:
            high_water = max(high_water, nav)
            drawdown = (high_water - nav) / high_water
            max_drawdown = max(max_drawdown, drawdown)
        
        # Current drawdown
        current_hwm = max(navs)
        current_nav = navs[-1]
        current_drawdown = (current_hwm - current_nav) / current_hwm
        
        return current_drawdown, max_drawdown, current_hwm
    
    def get_exposure_by_theme(self, theme_map: Dict[str, str]) -> Dict[str, float]:
        """
        Calculate exposure grouped by theme.
        
        Args:
            theme_map: Dict mapping strategy_name to theme
        
        Returns:
            Dict mapping theme to total exposure ($)
        """
        exposures: Dict[str, float] = {}
        
        for position in self.positions.values():
            theme = theme_map.get(position.strategy_name, "unknown")
            exposures[theme] = exposures.get(theme, 0.0) + position.max_loss
        
        return exposures
    
    def summary(self) -> Dict[str, Any]:
        """Generate a summary of current portfolio state."""
        current_dd, max_dd, hwm = self.calculate_drawdown()
        
        return {
            "cash": self.cash,
            "nav": self.nav,
            "total_return_pct": ((self.nav - self.initial_cash) / self.initial_cash) * 100,
            "open_positions": len(self.positions),
            "closed_positions": len(self.closed_positions),
            "total_premium_at_risk": self.total_premium_at_risk,
            "premium_at_risk_pct": (self.total_premium_at_risk / self.nav) * 100,
            "current_drawdown_pct": current_dd * 100,
            "max_drawdown_pct": max_dd * 100,
            "high_water_mark": hwm,
        }


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

if __name__ == "__main__":
    # Create a portfolio with $10,000
    portfolio = Portfolio(initial_cash=10000)
    
    # Create a VLO debit call spread
    vlo_spread = Position.create_spread(
        strategy_name="VLO_EARNINGS_CALL_SPREAD",
        underlying="VLO",
        long_strike=180.0,
        short_strike=195.0,
        expiration=date(2026, 2, 21),
        right=OptionRight.CALL,
        long_price=7.50,  # Pay $7.50 for 180 call
        short_price=3.50,  # Receive $3.50 for 195 call
        quantity=1,
        entry_timestamp=datetime(2026, 1, 27, 10, 30),
        entry_nav=10000,
    )
    
    print("=== VLO Spread Details ===")
    print(f"Net Premium (Debit): ${vlo_spread.net_premium:.2f}")
    print(f"Max Loss: ${vlo_spread.max_loss:.2f}")
    print(f"Max Profit: ${vlo_spread.max_profit:.2f}")
    
    # Open the position
    position_id = portfolio.open_position(vlo_spread)
    print(f"\nOpened position: {position_id}")
    print(f"Cash after entry: ${portfolio.cash:.2f}")
    
    # Create a SPY protective put
    spy_put = Position.create_single_option(
        strategy_name="SPY_PROTECTIVE_PUT",
        underlying="SPY",
        strike=560.0,
        expiration=date(2026, 2, 21),
        right=OptionRight.PUT,
        price=3.00,
        quantity=1,
        entry_timestamp=datetime(2026, 1, 21, 9, 35),
        entry_nav=10000,
    )
    
    portfolio.open_position(spy_put)
    
    print("\n=== Portfolio Summary ===")
    for key, value in portfolio.summary().items():
        print(f"{key}: {value}")
